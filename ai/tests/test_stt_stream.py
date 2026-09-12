"""The live path end to end: PCM in, utterances out, with the guards in place."""

import asyncio
import io
import re
import wave

import httpx
import pytest

from audio import RATE, silence, tone
from irya_ai.schemas.transcript import PassType, SpeakerRole
from irya_ai.stt.elice import EliceSttClient
from irya_ai.stt.stream import TranscriptionStream, silent_probe, wav_bytes

# One pause-delimited turn: enough speech to be worth a request, then a pause
# past the 700ms rule.
TURN = tone(1500) + silence(800)


def segment_index(request: httpx.Request) -> int:
    """Which segment a request carries, read back off the multipart filename."""

    match = re.search(rb'filename="seg_(\d+)\.wav"', request.content)
    assert match is not None
    return int(match.group(1))


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


def stream_for(handler, **kwargs) -> TranscriptionStream:
    client = EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid", transport=httpx.MockTransport(handler)
        ),
        retries=kwargs.pop("retries", 0),
        backoff_seconds=0.0,
    )
    return TranscriptionStream(
        client,
        session_id="ses_test",
        track_id="trk_candidate",
        speaker=SpeakerRole.CANDIDATE,
        **kwargs,
    )


async def test_a_turn_becomes_an_utterance() -> None:
    stream = stream_for(lambda request: ok("레디스로 캐시를 붙였습니다"))

    assert stream.push(TURN) == 1
    assert stream.close() == 0  # only the tail of the pause is left
    utterances = await stream.drain()

    assert len(utterances) == 1
    utterance = utterances[0]
    assert utterance.content == "레디스로 캐시를 붙였습니다"
    assert utterance.utterance_id == "utt_trk_candidate_0000"
    assert utterance.session_id == "ses_test"
    assert utterance.speaker is SpeakerRole.CANDIDATE
    assert utterance.pass_type is PassType.FINAL
    assert utterance.seq == 0
    assert utterance.start_ms == 0
    assert utterance.end_ms > utterance.start_ms
    assert stream.rejected == []


async def test_utterances_arrive_in_spoken_order_not_completion_order() -> None:
    """Out-of-order text is worse to read than slightly later text."""

    completed: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        index = segment_index(request)
        await asyncio.sleep(0.06 - 0.03 * index)  # the last segment answers first
        completed.append(index)
        return ok(f"문장 {index}")

    stream = stream_for(handler)
    stream.push(TURN * 3)
    stream.close()

    utterances = await stream.drain()

    assert [u.content for u in utterances] == ["문장 0", "문장 1", "문장 2"]
    assert [u.seq for u in utterances] == [0, 1, 2]
    assert completed == [2, 1, 0]
    assert [u.start_ms for u in utterances] == sorted(u.start_ms for u in utterances)


async def test_requests_in_flight_stay_within_the_limit() -> None:
    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return ok("네")

    stream = stream_for(handler, max_concurrency=2)
    stream.push(TURN * 5)
    stream.close()
    await stream.drain()

    assert peak == 2


async def test_each_guard_drops_its_own_kind_of_bad_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        index = segment_index(request)
        if index == 1:
            return ok("")
        if index == 2:
            # Whisper's stock answer to near-silence: a full-window span on a
            # segment that is only a couple of seconds long.
            return ok("시청해주셔서 감사합니다", end_s=29.98)
        if index == 3:
            return httpx.Response(500)
        return ok("실제 발화입니다")

    stream = stream_for(handler)
    stream.push(TURN * 4)
    stream.close()

    utterances = await stream.drain()

    assert [u.content for u in utterances] == ["실제 발화입니다"]
    assert [reason for _, reason in stream.rejected] == [
        "EMPTY",
        "TIMESTAMP_OVERRUN",
        "REQUEST_FAILED",
    ]


async def test_a_rejected_segment_does_not_consume_a_sequence_number() -> None:
    """seq orders what the reader sees, so it must have no holes in it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if segment_index(request) == 0:
            return ok("")
        return ok("남은 발화")

    stream = stream_for(handler)
    stream.push(TURN * 3)
    stream.close()

    utterances = await stream.drain()

    assert [u.seq for u in utterances] == [0, 1]


async def test_close_sends_the_tail_that_never_got_a_pause() -> None:
    """The last answer of an interview rarely ends with a 700ms pause."""

    stream = stream_for(lambda request: ok("마지막 문장입니다"))

    assert stream.push(tone(2000)) == 0
    assert stream.close() == 1
    utterances = await stream.drain()

    assert [u.content for u in utterances] == ["마지막 문장입니다"]


async def test_closing_twice_is_harmless_and_pushing_after_close_is_not() -> None:
    stream = stream_for(lambda request: ok("네"))
    stream.push(TURN)
    stream.close()

    assert stream.close() == 0
    with pytest.raises(RuntimeError, match="closed"):
        stream.push(TURN)

    await stream.drain()


async def test_draining_an_empty_stream_yields_nothing() -> None:
    stream = stream_for(lambda request: ok("네"))

    stream.push(silence(3000))
    stream.close()

    assert await stream.drain() == []


def test_wav_bytes_wraps_pcm_the_way_the_service_expects() -> None:
    pcm = tone(500)

    with wave.open(io.BytesIO(wav_bytes(pcm, RATE)), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == RATE
        assert handle.readframes(handle.getnframes()) == pcm


def test_silent_probe_is_a_readable_wav_of_the_asked_length() -> None:
    with wave.open(io.BytesIO(silent_probe(duration_ms=1500)), "rb") as handle:
        assert handle.getnframes() == RATE * 3 // 2
        assert set(handle.readframes(handle.getnframes())) == {0}
