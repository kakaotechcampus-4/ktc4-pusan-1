"""Recording in, a REALIGNED snapshot out, on the live path's session clock."""

import wave
from pathlib import Path

import av
import httpx
import pytest

from audio import RATE, silence, tone
from irya_ai.schemas.transcript import SpeakerRole, TranscriptStage
from irya_ai.stt.elice import EliceSttClient
from irya_ai.stt.realign import (
    RealignError,
    RecordedTrack,
    decode_pcm,
    realign,
)

ORIGIN_MS = 1_760_000_000_000


def ok(text: str, end_s: float = 1.0) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "text": text,
            "segments": [{"id": 0, "start": 0.0, "end": end_s, "text": text}],
        },
    )


def client_for(handler) -> EliceSttClient:
    return EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid", transport=httpx.MockTransport(handler)
        ),
        retries=0,
        backoff_seconds=0.0,
    )


def write_wav(path: Path, pcm: bytes) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm)
    return path


def track(tmp_path: Path, name: str, pcm: bytes, *, started_ms: int) -> RecordedTrack:
    path = write_wav(tmp_path / f"{name}.wav", pcm)
    return RecordedTrack.from_egress(path, started_ms * 1_000_000)


def test_speaker_and_track_come_from_the_egress_file_name() -> None:
    recorded = RecordedTrack.from_egress(
        Path("rec/ses_1/CANDIDATE-TR_AMkq7.ogg"), 1_500_000_123
    )

    assert recorded.speaker is SpeakerRole.CANDIDATE
    assert recorded.track_id == "TR_AMkq7"
    assert recorded.started_ms == 1500


@pytest.mark.parametrize(
    "name", ["OBSERVER-TR_1.ogg", "CANDIDATE.ogg", "CANDIDATE-.ogg"]
)
def test_a_file_that_does_not_name_a_speaker_and_track_is_refused(name: str) -> None:
    with pytest.raises(RealignError):
        RecordedTrack.from_egress(Path(name), 0)


async def test_each_track_lands_at_its_own_offset_on_the_session_clock(
    tmp_path: Path,
) -> None:
    interviewer = track(
        tmp_path,
        "INTERVIEWER-TR_i",
        tone(1500) + silence(800),
        started_ms=ORIGIN_MS + 1000,
    )
    candidate = track(
        tmp_path,
        "CANDIDATE-TR_c",
        silence(1000) + tone(1500) + silence(800),
        started_ms=ORIGIN_MS + 2000,
    )

    result = await realign(
        client_for(lambda request: ok("네")),
        session_id="ses_1",
        origin_ms=ORIGIN_MS,
        tracks=[candidate, interviewer],
    )

    snapshot = result.snapshot
    assert snapshot.stage is TranscriptStage.REALIGNED
    assert [u.speaker for u in snapshot.utterances] == [
        SpeakerRole.INTERVIEWER,
        SpeakerRole.CANDIDATE,
    ]
    first, second = snapshot.utterances
    assert first.start_ms == 1000
    # 2s into the session, then the candidate's 1s of leading silence. The
    # segmenter starts the segment at the stream head, not at the voice, so
    # the start can only be pinned to within that silence.
    assert 2000 <= second.start_ms <= 3000
    assert first.utterance_id == "utt_TR_i_r0000"
    assert second.track_id == "TR_c"
    assert result.complete


async def test_a_recording_that_starts_before_the_origin_is_trimmed_not_shifted(
    tmp_path: Path,
) -> None:
    # 600ms of audio from before the origin, then speech exactly at the origin.
    candidate = track(
        tmp_path,
        "CANDIDATE-TR_c",
        tone(600, amplitude=50) + tone(1500) + silence(800),
        started_ms=ORIGIN_MS - 600,
    )

    result = await realign(
        client_for(lambda request: ok("네")),
        session_id="ses_1",
        origin_ms=ORIGIN_MS,
        tracks=[candidate],
    )

    (utterance,) = result.snapshot.utterances
    assert utterance.start_ms == 0
    assert utterance.end_ms <= 2300 + 20


async def test_a_long_turn_is_sent_whole_rather_than_cut_at_the_live_cap(
    tmp_path: Path,
) -> None:
    requests: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(len(request.content))
        return ok("긴 답변", end_s=12.0)

    candidate = track(
        tmp_path, "CANDIDATE-TR_c", tone(12_000) + silence(800), started_ms=ORIGIN_MS
    )

    result = await realign(
        client_for(handler),
        session_id="ses_1",
        origin_ms=ORIGIN_MS,
        tracks=[candidate],
    )

    assert len(requests) == 1
    (utterance,) = result.snapshot.utterances
    assert utterance.end_ms - utterance.start_ms >= 12_000


async def test_a_failed_request_marks_the_result_incomplete(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503) if calls == 1 else ok("")

    candidate = track(
        tmp_path,
        "CANDIDATE-TR_c",
        (tone(1500) + silence(800)) * 2,
        started_ms=ORIGIN_MS,
    )

    result = await realign(
        client_for(handler),
        session_id="ses_1",
        origin_ms=ORIGIN_MS,
        tracks=[candidate],
        concurrency=1,
    )

    assert result.snapshot.utterances == []
    assert [d.reason for d in result.dropped] == ["REQUEST_FAILED", "EMPTY"]
    assert result.failed[0].code == "STT_REQUEST_FAILED"
    assert not result.complete


async def test_a_stamp_past_the_audio_is_dropped_but_does_not_fail_the_pass(
    tmp_path: Path,
) -> None:
    candidate = track(
        tmp_path, "CANDIDATE-TR_c", tone(1500) + silence(800), started_ms=ORIGIN_MS
    )

    result = await realign(
        client_for(lambda request: ok("시청해 주셔서 감사합니다", end_s=29.98)),
        session_id="ses_1",
        origin_ms=ORIGIN_MS,
        tracks=[candidate],
    )

    assert result.snapshot.utterances == []
    assert [d.reason for d in result.dropped] == ["TIMESTAMP_OVERRUN"]
    assert result.complete


def test_an_opus_recording_decodes_to_the_same_length(tmp_path: Path) -> None:
    path = tmp_path / "CANDIDATE-TR_c.ogg"
    with av.open(str(path), "w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=48000, layout="mono")
        frame = av.AudioFrame(format="s16", layout="mono", samples=RATE * 2)
        frame.planes[0].update(tone(2000))
        frame.sample_rate = RATE
        frame.pts = 0
        resampler = av.AudioResampler(format=stream.format, layout="mono", rate=48000)
        for out in [*resampler.resample(frame), *resampler.resample(None)]:
            container.mux(stream.encode(out))
        container.mux(stream.encode(None))

    pcm = b"".join(decode_pcm(path, sample_rate=RATE))

    # Opus pads its first and last packets, so allow a frame either way.
    assert abs(len(pcm) // 2 - RATE * 2) <= RATE * 30 // 1000


def test_a_file_that_is_not_audio_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "CANDIDATE-TR_c.ogg"
    path.write_bytes(b"not an ogg")

    with pytest.raises(RealignError, match="REALIGN_UNREADABLE"):
        list(decode_pcm(path, sample_rate=RATE))
