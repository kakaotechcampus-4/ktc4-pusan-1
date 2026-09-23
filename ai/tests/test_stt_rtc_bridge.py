"""RTC frames into the Whisper stream, utterances out to the interviewer."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from livekit import rtc

from audio import RATE, silence, tone
from irya_ai.schemas.transcript import SpeakerRole, Utterance
from irya_ai.stt.elice import EliceSttClient
from irya_ai.stt.rtc_bridge import (
    DEGRADED_REASON,
    NUM_CHANNELS,
    SAMPLE_RATE,
    TRANSCRIPT_TOPIC,
    LiveKitTextSink,
    RoomTranscriber,
    degraded_event_json,
    frame_pcm,
    session_id_from_room,
    speaker_from_identity,
    transcribe_audio_frames,
    transcript_event_json,
)
from irya_ai.stt.stream import TranscriptionStream

FRAME_MS = 20
FRAME_BYTES = RATE * FRAME_MS // 1000 * 2  # 16-bit mono


def frame(pcm: bytes, *, sample_rate: int = RATE, channels: int = 1) -> rtc.AudioFrame:
    return rtc.AudioFrame(
        data=pcm,
        sample_rate=sample_rate,
        num_channels=channels,
        samples_per_channel=len(pcm) // (2 * channels),
    )


def chunked(pcm: bytes) -> list[rtc.AudioFrame]:
    """The way the SDK hands audio over: a frame every few milliseconds."""

    return [frame(pcm[i : i + FRAME_BYTES]) for i in range(0, len(pcm), FRAME_BYTES)]


async def frames(*values: rtc.AudioFrame):
    for value in values:
        yield value


def utterance(**overrides) -> Utterance:
    fields = {
        "utterance_id": "utt_track_0000",
        "session_id": "ses_123",
        "track_id": "track",
        "speaker": SpeakerRole.CANDIDATE,
        "seq": 16,
        "start_ms": 1250,
        "end_ms": 2400,
        "content": "레디스로 캐시를 붙였습니다",
    }
    return Utterance(**{**fields, **overrides})


class FakeStream:
    """Stands in for ``TranscriptionStream``: records audio, replays utterances.

    Utterances are released once the stream is closed, the way the real one
    releases the tail, unless ``fail_with`` is set - then iterating raises
    it, the way a sink or a broken client would.
    """

    def __init__(
        self, utterances: list[Utterance], *, fail_with: Exception | None = None
    ) -> None:
        self.utterances = utterances
        self.fail_with = fail_with
        self.pushed: list[bytes] = []
        self.closed = asyncio.Event()
        self.abandoned = False

    def push(self, pcm: bytes) -> int:
        if self.closed.is_set():
            raise RuntimeError("cannot push into a closed stream")
        self.pushed.append(pcm)
        return 0

    def close(self) -> int:
        self.closed.set()
        return 0

    async def aclose(self) -> None:
        self.abandoned = True
        self.closed.set()

    async def __aiter__(self):
        if self.fail_with is not None:
            raise self.fail_with
        await self.closed.wait()
        for value in self.utterances:
            yield value


class FakeLocalParticipant:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def send_text(self, payload: str, **kwargs) -> None:
        self.sent.append((payload, kwargs))


def stt_client(handler) -> EliceSttClient:
    return EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid", transport=httpx.MockTransport(handler)
        ),
        retries=0,
        backoff_seconds=0.0,
    )


def ok(text: str, end_s: float = 1.0) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "_result": {"status": "ok", "reason": None},
            "transcript": {
                "text": text,
                "chunks": [{"timestamp": [0.0, end_s], "text": text}],
            },
        },
    )


# --- frames in, utterances out ------------------------------------------------


async def test_frames_flow_into_the_stream_and_utterances_reach_every_sink() -> None:
    stream = FakeStream([utterance()])
    first: list[Utterance] = []
    second: list[Utterance] = []

    async def sink_one(value: Utterance) -> None:
        first.append(value)

    async def sink_two(value: Utterance) -> None:
        second.append(value)

    audio = [frame(b"\x01\x00" * 160), frame(b"\x02\x00" * 160)]
    result = await transcribe_audio_frames(
        frames=frames(*audio),
        stream_factory=lambda: stream,
        sinks=[sink_one, sink_two],
    )

    assert result is stream
    assert stream.pushed == [b"\x01\x00" * 160, b"\x02\x00" * 160]
    assert stream.closed.is_set(), "the track ending flushes the tail"
    assert stream.abandoned, "and the stream is released either way"
    assert [v.content for v in first] == ["레디스로 캐시를 붙였습니다"]
    assert first == second


async def test_an_empty_track_opens_no_stream() -> None:
    def factory():
        raise AssertionError("no stream expected")

    async def sink(_value: Utterance) -> None:
        raise AssertionError("no utterance expected")

    assert (
        await transcribe_audio_frames(
            frames=frames(), stream_factory=factory, sinks=[sink]
        )
        is None
    )


async def test_a_dying_consumer_stops_the_pump_and_abandons_the_stream() -> None:
    stream = FakeStream([], fail_with=RuntimeError("stt is gone"))
    pumped = 0

    async def endless():
        nonlocal pumped
        while True:
            pumped += 1
            yield frame(b"\x00\x00" * 160)
            await asyncio.sleep(0)

    async def sink(_value: Utterance) -> None:
        raise AssertionError("no utterance expected")

    with pytest.raises(RuntimeError, match="stt is gone"):
        await transcribe_audio_frames(
            frames=endless(), stream_factory=lambda: stream, sinks=[sink]
        )

    assert stream.abandoned
    assert pumped < 100, "the pump was cancelled rather than left running"


async def test_a_failing_sink_ends_the_track_the_same_way() -> None:
    stream = FakeStream([utterance()])

    async def sink(_value: Utterance) -> None:
        raise ConnectionError("room went away")

    with pytest.raises(ConnectionError):
        await transcribe_audio_frames(
            frames=frames(frame(b"\x00\x00" * 160)),
            stream_factory=lambda: stream,
            sinks=[sink],
        )

    assert stream.abandoned


def test_frames_in_the_wrong_shape_are_refused_not_transcribed() -> None:
    assert frame_pcm(frame(b"\x01\x00" * 160)) == b"\x01\x00" * 160
    with pytest.raises(ValueError, match="48000 Hz"):
        frame_pcm(frame(b"\x00\x00" * 480, sample_rate=48_000))
    with pytest.raises(ValueError, match="x2"):
        frame_pcm(frame(b"\x00\x00" * 320, channels=2))
    assert (SAMPLE_RATE, NUM_CHANNELS) == (RATE, 1)


async def test_a_real_stream_turns_a_spoken_turn_into_a_caption() -> None:
    """End to end below the room: SDK-sized frames -> segmenter -> Whisper -> sink."""

    client = stt_client(lambda request: ok("레디스로 캐시를 붙였습니다"))
    stream = TranscriptionStream(
        client,
        session_id="ses_123",
        track_id="trk_candidate",
        speaker=SpeakerRole.CANDIDATE,
    )
    received: list[Utterance] = []

    async def sink(value: Utterance) -> None:
        received.append(value)

    turn = tone(1500) + silence(800)
    result = await transcribe_audio_frames(
        frames=frames(*chunked(turn)), stream_factory=lambda: stream, sinks=[sink]
    )

    assert result is stream
    assert [v.content for v in received] == ["레디스로 캐시를 붙였습니다"]
    assert received[0].utterance_id == "utt_trk_candidate_0000"
    assert received[0].speaker is SpeakerRole.CANDIDATE
    assert stream.rejected == []


# --- the interviewer boundary -------------------------------------------------


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


# --- the room ----------------------------------------------------------------


def transcriber(**kwargs) -> RoomTranscriber:
    kwargs.setdefault("room", SimpleNamespace(local_participant=FakeLocalParticipant()))
    kwargs.setdefault("session_id", "ses_123")
    kwargs.setdefault("client", stt_client(lambda request: ok("")))
    return RoomTranscriber(**kwargs)


def test_room_origin_uses_the_earliest_human_join() -> None:
    now = datetime(2026, 9, 18, 7, 0, tzinfo=UTC)
    room = transcriber(wall_clock=lambda: now + timedelta(seconds=30))
    participants = [
        SimpleNamespace(
            identity="agent-observer", joined_at=now - timedelta(seconds=1)
        ),
        SimpleNamespace(identity="CANDIDATE", joined_at=now + timedelta(seconds=5)),
        SimpleNamespace(identity="INTERVIEWER", joined_at=now),
    ]

    assert room.initialize_origin(participants) == now  # type: ignore[arg-type]
    assert room.initialize_origin([]) == now


def test_empty_room_waits_for_the_first_human_before_pinning_origin() -> None:
    now = datetime(2026, 9, 18, 7, 0, tzinfo=UTC)
    room = transcriber(wall_clock=lambda: now)

    assert room.initialize_origin([]) is None
    candidate_joined_at = now + timedelta(minutes=10)
    assert (
        room.initialize_origin(
            [SimpleNamespace(identity="CANDIDATE", joined_at=candidate_joined_at)]
        )
        == candidate_joined_at
    )


def test_a_track_is_placed_on_the_session_timeline_where_its_audio_starts() -> None:
    now = datetime(2026, 9, 18, 7, 0, tzinfo=UTC)
    room = transcriber(wall_clock=lambda: now + timedelta(seconds=12, milliseconds=500))
    room.initialize_origin([SimpleNamespace(identity="INTERVIEWER", joined_at=now)])

    stream = room.stream_for("trk_1", SpeakerRole.INTERVIEWER)

    assert isinstance(stream, TranscriptionStream)
    assert stream.ordering.offset_ms == 12_500
    assert stream.speaker is SpeakerRole.INTERVIEWER
    assert stream.session_id == "ses_123"
    assert [t.track_id for t in room.ordering.tracks] == ["trk_1"]


def test_the_caption_is_the_default_sink_and_others_can_replace_it() -> None:
    async def other(_value: Utterance) -> None:
        pass

    room = transcriber()
    assert room.sinks == [room.caption]
    assert transcriber(sinks=[other]).sinks == [other]


def test_room_transcriber_can_be_created_before_room_connects() -> None:
    class DisconnectedRoom:
        @property
        def local_participant(self):
            raise AssertionError("local participant accessed before connect")

    transcriber(room=DisconnectedRoom())
