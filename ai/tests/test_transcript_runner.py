"""FINAL fan-out reaches a real WebSocket without waiting in the caption path."""

import asyncio

from irya_ai.backend import BackendError
from irya_ai.schemas.transcript import Utterance
from irya_ai.sinks import FanOutSink
from irya_ai.transcript_runner import TranscriptRunner
from test_transcripts import FakeBackend, channel_for, eventually


def utterance(index=0, **changes):
    return Utterance.model_validate(
        {
            "utteranceId": f"utt_{index}",
            "sessionId": "ses_123",
            "trackId": "TR_candidate",
            "speaker": "CANDIDATE",
            "seq": index,
            "startMs": index * 1000,
            "endMs": index * 1000 + 500,
            "content": "합성 시험 발화입니다.",
            **changes,
        }
    )


async def test_finals_keep_order_and_identity_and_wait_for_ack_on_stop():
    async with FakeBackend() as backend:
        channel = channel_for(backend)
        runner = TranscriptRunner(channel, session_id="ses_123")
        runner.start()
        await runner(utterance(passType="INTERIM"))
        for index in range(3):
            await runner(utterance(index))
        await runner.stop()
        assert [f["seq"] for f in backend.frames()] == [0, 1, 2]
        assert all(f["participantId"] == "CANDIDATE" for f in backend.frames())
        assert all(f["trackId"] == "TR_candidate" for f in backend.frames())
        assert channel.unacknowledged == 0
        assert runner.dropped == 0
        await runner.stop()
        await runner(utterance(4))
        assert runner.dropped == 1


async def test_stalled_handshake_does_not_block_captions_and_queue_is_bounded():
    release = asyncio.Event()
    async with FakeBackend(stall=release) as backend:
        channel = channel_for(backend)
        runner = TranscriptRunner(channel, session_id="ses_123", max_queue=1)
        runner.start()
        captions = []

        async def caption(u):
            captions.append(u.utterance_id)

        sink = FanOutSink([caption, runner])
        try:
            await sink(utterance())
            await eventually(lambda: bool(backend.handshakes))
            # Connection is still stalled. A network await in the sink would
            # time out here and prevent the next caption from being delivered.
            await asyncio.wait_for(sink(utterance(1)), 0.1)
            await asyncio.wait_for(sink(utterance(2)), 0.1)
            assert captions == ["utt_0", "utt_1", "utt_2"]
            assert runner.dropped == 1
        finally:
            release.set()
            await runner.stop()
        assert [f["utteranceId"] for f in backend.frames()] == ["utt_0", "utt_1"]


async def test_caption_failure_does_not_lose_the_backend_transcript():
    async with FakeBackend() as backend:
        channel = channel_for(backend)
        runner = TranscriptRunner(channel, session_id="ses_123")
        runner.start()

        async def caption(u):
            raise RuntimeError("caption transport unavailable")

        await FanOutSink([caption, runner])(utterance())
        await runner.stop()
        assert len(backend.frames()) == 1
        assert channel.unacknowledged == 0


async def test_nack_drops_only_refused_frame_and_following_final_is_acked():
    async with FakeBackend(nack={"utt_0": "SCHEMA"}) as backend:
        channel = channel_for(backend)
        runner = TranscriptRunner(channel, session_id="ses_123")
        runner.start()
        await runner(utterance())
        await runner(utterance(1))
        await runner.stop()
        assert channel.refused == {"utt_0": "SCHEMA"}
        assert len(backend.frames()) == 2
        assert channel.unacknowledged == 0


async def test_reconnect_resends_the_same_final_id_and_original_seq():
    async with FakeBackend(ack=False, drop_first_after=1) as backend:
        channel = channel_for(backend, ack_timeout_seconds=0.1)
        runner = TranscriptRunner(channel, session_id="ses_123")
        runner.start()
        try:
            backend.reply = lambda frame: (
                {"type": "transcript.ack", "utteranceId": frame["utteranceId"]}
                if backend.connections > 1
                else None
            )
            await runner(utterance(7))
            await eventually(lambda: channel.unacknowledged == 0 and backend.frames())
        finally:
            await runner.stop()
        assert all(f["utteranceId"] == "utt_7" for f in backend.frames())
        assert all(f["seq"] == 7 for f in backend.frames())


class BrokenChannel:
    unacknowledged = 0
    refused = {}

    def __init__(self):
        self.sent = []
        self.closed = False
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()

    async def send(self, payload):
        self.sent.append(payload)
        if len(self.sent) == 1:
            raise BackendError("BACKEND_AUTH_FAILED", retryable=False)
        self.blocked.set()
        await self.release.wait()

    async def aclose(self):
        self.closed = True


async def test_permanent_failure_and_shutdown_timeout_do_not_kill_or_leak_task():
    channel = BrokenChannel()
    runner = TranscriptRunner(channel, session_id="ses_123", max_queue=2)
    task = runner.start()
    await runner(utterance())
    await eventually(lambda: runner.send_failures == 1)
    await runner(utterance(1))
    await channel.blocked.wait()
    await runner(utterance(2))
    await runner.stop(timeout=0.01)
    assert task.done()
    assert channel.closed
    assert runner.dropped == 2  # auth refusal + unsent queued final


async def test_other_session_is_not_sent_and_invalid_payload_text_is_not_logged(caplog):
    async with FakeBackend() as backend:
        channel = channel_for(backend)
        runner = TranscriptRunner(channel, session_id="ses_123")
        runner.start()
        await runner(utterance(sessionId="ses_other"))
        await runner(utterance(trackId="", content="private synthetic sentinel"))
        await runner.stop()
        assert runner.dropped == 2
        assert backend.frames() == []
        assert "private synthetic sentinel" not in caplog.text
