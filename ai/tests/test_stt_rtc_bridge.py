"""RTC frames, provider events, and the interviewer delivery boundary."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from livekit.agents import stt as livekit_stt

from irya_ai.schemas.transcript import SpeakerRole, Utterance
from irya_ai.stt.cartesia import CartesiaTranscriptionStream
from irya_ai.stt.rtc_bridge import (
    DEGRADED_REASON,
    TRANSCRIPT_TOPIC,
    LiveKitTextSink,
    RoomTranscriber,
    degraded_event_json,
    session_id_from_room,
    speaker_from_identity,
    transcribe_audio_frames,
    transcript_event_json,
)


def final(text: str, start_s: float, end_s: float) -> livekit_stt.SpeechEvent:
    return livekit_stt.SpeechEvent(
        type=livekit_stt.SpeechEventType.FINAL_TRANSCRIPT,
        alternatives=[
            livekit_stt.SpeechData(
                language="ko", text=text, start_time=start_s, end_time=end_s
            )
        ],
    )


async def frames(*values):
    for value in values:
        yield value


class FakeSpeechStream:
    def __init__(self, events: list[livekit_stt.SpeechEvent]) -> None:
        self.events = events
        self.pushed: list[object] = []
        self.input_ended = asyncio.Event()
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> None:
        self.closed = True

    def push_frame(self, frame) -> None:
        self.pushed.append(frame)

    def end_input(self) -> None:
        self.input_ended.set()

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        await self.input_ended.wait()
        for event in self.events:
            yield event


class FakeSTT:
    def __init__(self, stream: FakeSpeechStream) -> None:
        self.provider_stream = stream
        self.stream_calls = 0

    def stream(self) -> FakeSpeechStream:
        self.stream_calls += 1
        return self.provider_stream


class FakeLocalParticipant:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def send_text(self, payload: str, **kwargs) -> None:
        self.sent.append((payload, kwargs))


def utterance() -> Utterance:
    return Utterance(
        utterance_id="utt_track_0000",
        session_id="ses_123",
        track_id="track",
        speaker=SpeakerRole.CANDIDATE,
        seq=16,
        start_ms=1250,
        end_ms=2400,
        content="레디스로 캐시를 붙였습니다",
    )


async def test_frames_flow_to_provider_and_final_flows_to_sink() -> None:
    provider_stream = FakeSpeechStream([final("레디스로 캐시를", 0.0, 1.0)])
    stt = FakeSTT(provider_stream)
    ticks = iter([10.0, 11.2])
    received: list[Utterance] = []

    def converter_factory() -> CartesiaTranscriptionStream:
        return CartesiaTranscriptionStream(
            session_id="ses_123",
            track_id="track",
            speaker=SpeakerRole.CANDIDATE,
            clock=lambda: next(ticks),
        )

    async def sink(value: Utterance) -> None:
        received.append(value)

    converter = await transcribe_audio_frames(
        frames=frames("one", "two", "three"),
        stt=stt,
        converter_factory=converter_factory,
        sink=sink,
    )

    assert provider_stream.pushed == ["one", "two", "three"]
    assert provider_stream.input_ended.is_set()
    assert provider_stream.closed
    assert [value.content for value in received] == ["레디스로 캐시를"]
    assert converter is not None
    assert converter.timings[0].lag_ms == 200


async def test_an_empty_track_does_not_open_a_paid_provider_stream() -> None:
    provider_stream = FakeSpeechStream([])
    stt = FakeSTT(provider_stream)
    factory_called = False

    def converter_factory() -> CartesiaTranscriptionStream:
        nonlocal factory_called
        factory_called = True
        raise AssertionError("no converter expected")

    async def sink(_value: Utterance) -> None:
        raise AssertionError("no utterance expected")

    converter = await transcribe_audio_frames(
        frames=frames(),
        stt=stt,
        converter_factory=converter_factory,
        sink=sink,
    )

    assert converter is None
    assert stt.stream_calls == 0
    assert not factory_called


async def test_livekit_sink_targets_only_the_interviewer() -> None:
    participant = FakeLocalParticipant()
    room = SimpleNamespace(local_participant=participant)
    sink = LiveKitTextSink(room)  # type: ignore[arg-type]

    await sink(utterance())
    await sink.degraded()

    assert len(participant.sent) == 2
    transcript_payload, transcript_options = participant.sent[0]
    assert json.loads(transcript_payload) == {
        "type": "transcript.delta",
        "utteranceId": "utt_track_0000",
        "speaker": "CANDIDATE",
        "text": "레디스로 캐시를 붙였습니다",
        "at": 1.25,
        "final": True,
    }
    assert transcript_options == {
        "topic": TRANSCRIPT_TOPIC,
        "destination_identities": ["INTERVIEWER"],
    }
    assert json.loads(participant.sent[1][0]) == {
        "type": "stream.degraded",
        "reason": DEGRADED_REASON,
    }


def test_wire_helpers_are_compact_and_keep_korean() -> None:
    assert "레디스로" in transcript_event_json(utterance())
    assert " " not in degraded_event_json()


def test_room_and_identity_mapping_accept_only_irya_values() -> None:
    assert session_id_from_room("interview_ses_123") == "ses_123"
    assert session_id_from_room("interview_") is None
    assert session_id_from_room("demo_ses_123") is None
    assert speaker_from_identity("INTERVIEWER") is SpeakerRole.INTERVIEWER
    assert speaker_from_identity("CANDIDATE") is SpeakerRole.CANDIDATE
    assert speaker_from_identity("agent") is None


def test_room_origin_uses_the_earliest_human_join() -> None:
    now = datetime(2026, 9, 18, 7, 0, tzinfo=UTC)
    local = FakeLocalParticipant()
    room = SimpleNamespace(local_participant=local)
    transcriber = RoomTranscriber(
        room=room,  # type: ignore[arg-type]
        session_id="ses_123",
        stt=FakeSTT(FakeSpeechStream([])),
        wall_clock=lambda: now + timedelta(seconds=30),
    )
    participants = [
        SimpleNamespace(
            identity="agent-observer", joined_at=now - timedelta(seconds=1)
        ),
        SimpleNamespace(identity="CANDIDATE", joined_at=now + timedelta(seconds=5)),
        SimpleNamespace(identity="INTERVIEWER", joined_at=now),
    ]

    assert transcriber.initialize_origin(participants) == now  # type: ignore[arg-type]
    assert transcriber.initialize_origin([]) == now


def test_empty_room_waits_for_the_first_human_before_pinning_origin() -> None:
    now = datetime(2026, 9, 18, 7, 0, tzinfo=UTC)
    room = SimpleNamespace(local_participant=FakeLocalParticipant())
    transcriber = RoomTranscriber(
        room=room,  # type: ignore[arg-type]
        session_id="ses_123",
        stt=FakeSTT(FakeSpeechStream([])),
        wall_clock=lambda: now,
    )

    assert transcriber.initialize_origin([]) is None
    candidate_joined_at = now + timedelta(minutes=10)
    assert (
        transcriber.initialize_origin(
            [SimpleNamespace(identity="CANDIDATE", joined_at=candidate_joined_at)]
        )
        == candidate_joined_at
    )


def test_room_transcriber_can_be_created_before_room_connects() -> None:
    class DisconnectedRoom:
        @property
        def local_participant(self):
            raise AssertionError("local participant accessed before connect")

    RoomTranscriber(
        room=DisconnectedRoom(),  # type: ignore[arg-type]
        session_id="ses_123",
        stt=FakeSTT(FakeSpeechStream([])),
    )
