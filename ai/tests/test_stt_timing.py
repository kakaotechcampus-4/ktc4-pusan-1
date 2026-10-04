"""What the latency numbers actually measure, on a clock the test controls.

The PR's published figure is segment duration plus request time. That is not
display lag, and it is not even the whole in-process wait: it starts at the
segment's end rather than at its first sample, so it skips the audio the
segmenter had already captured while it made up its mind; it skips the wait
for an admission slot and for a concurrency slot; and it skips the wait behind
an older segment that had not answered yet. These tests pin each of those
waits separately, and pin the gap between the two figures.

Nothing here touches a real clock: the stream's ``clock`` is injected and only
moves when a handler or the test moves it, so the numbers are exact.
"""

import asyncio
import re

import httpx
import pytest

from audio import silence, tone
from irya_ai.schemas.transcript import SpeakerRole
from irya_ai.stt.elice import EliceSttClient
from irya_ai.stt.segmentation import CutReason, SegmentationConfig
from irya_ai.stt.stream import TranscriptionStream

TURN = tone(1500) + silence(800)


class FakeClock:
    """Monotonic time that only moves when the test moves it."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def segment_index(request: httpx.Request) -> int:
    match = re.search(rb'filename="seg_(\d+)\.wav"', request.content)
    assert match is not None
    return int(match.group(1))


def ok(text: str = "문장") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "_result": {"status": "ok", "reason": None},
            "transcript": {
                "text": text,
                "chunks": [{"timestamp": [0.0, 1.0], "text": text}],
            },
        },
    )


def stream_for(handler, clock, **kwargs) -> TranscriptionStream:
    client = EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid", transport=httpx.MockTransport(handler)
        ),
        retries=0,
        backoff_seconds=0.0,
    )
    return TranscriptionStream(
        client,
        session_id="ses_test",
        track_id="trk_candidate",
        speaker=SpeakerRole.CANDIDATE,
        clock=clock,
        **kwargs,
    )


async def test_a_forced_cut_had_already_captured_audio_past_its_end() -> None:
    """The lookback the published figure starts after, measured."""

    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now = 0.4
        return ok()

    # Unbroken speech past the 5s cap: the cut is forced and then moved back
    # into the quiet-search window, so it lands before the audio already held.
    stream = stream_for(handler, clock)
    stream.push(tone(6000) + silence(800))
    stream.close()
    await asyncio.wait_for(stream.drain(), timeout=5)

    forced = [t for t in stream.timings if t.cut_reason is CutReason.FORCED]
    assert forced, "expected the 5s cap to force a cut"
    timing = forced[0]
    assert timing.decision_lag_ms > 0
    assert timing.received_ms > timing.end_ms
    # The audio was captured; the decision about it had not been made yet.
    assert timing.first_sample_wait_ms == timing.duration_ms + timing.decision_lag_ms


async def test_waiting_for_a_concurrency_slot_is_counted() -> None:
    """One request at a time: the second segment queues, and it shows."""

    clock = FakeClock()
    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if segment_index(request) == 0:
            await gate.wait()
            return ok("느린 첫 문장")
        clock.now = 1.3
        return ok("두 번째")

    stream = stream_for(handler, clock, max_concurrency=1)
    stream.push(TURN * 2)
    stream.close()

    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0.01)
    clock.now = 1.0
    gate.set()
    utterances = await asyncio.wait_for(consumer, timeout=5)

    assert len(utterances) == 2
    first, second = stream.timings
    assert first.queue_wait_ms == 0
    assert second.queue_wait_ms == 1000
    assert second.request_ms == 300


async def test_a_slow_head_holds_back_a_segment_that_already_answered() -> None:
    """Order is a contract, so answering early buys the one behind nothing."""

    clock = FakeClock()
    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if segment_index(request) == 0:
            await gate.wait()
            return ok("느린 첫 문장")
        clock.now = 0.2
        return ok("일찍 끝난 두 번째")

    stream = stream_for(handler, clock, max_concurrency=2)
    stream.push(TURN * 2)
    stream.close()

    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0.01)
    first, second = stream.timings
    assert second.request_ended_at is not None, "the second answered first"
    assert second.released_at is None, "and is still waiting on the first"

    clock.now = 2.0
    gate.set()
    await asyncio.wait_for(consumer, timeout=5)

    assert first.head_of_line_wait_ms == 0
    assert second.head_of_line_wait_ms == 1800
    assert second.request_ms == 200


async def test_the_published_figure_is_lower_than_the_wait_it_stands_for() -> None:
    """``proxy_display_lag_ms`` is short by exactly the waits it leaves out."""

    clock = FakeClock()
    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if segment_index(request) == 0:
            await gate.wait()
            return ok("느린 첫 문장")
        clock.now = 0.2
        return ok("두 번째")

    stream = stream_for(handler, clock, max_concurrency=2)
    stream.push(tone(6000) + silence(800) + tone(1500) + silence(800))
    stream.close()

    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0.01)
    clock.now = 2.0
    gate.set()
    await asyncio.wait_for(consumer, timeout=5)

    for timing in stream.timings:
        assert timing.proxy_display_lag_ms is not None
        assert timing.source_to_release_ms is not None
        assert timing.source_to_release_ms > timing.proxy_display_lag_ms

    held = stream.timings[1]
    # The whole difference is accounted for, not merely larger.
    assert held.source_to_release_ms - held.proxy_display_lag_ms == (
        held.decision_lag_ms + held.queue_wait_ms + held.head_of_line_wait_ms
    )


async def test_the_n1_figure_starts_where_the_speaker_stopped() -> None:
    """``speech_end_to_release_ms`` drops the segment's own length, nothing else."""

    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now += 0.3
        return ok()

    # One quiet cut and one forced cut, so decision lag is both zero and not.
    stream = stream_for(handler, clock)
    stream.push(TURN + tone(6000) + silence(800))
    stream.close()
    await asyncio.wait_for(stream.drain(), timeout=5)

    assert {t.cut_reason for t in stream.timings} >= {CutReason.FORCED}
    for timing in stream.timings:
        assert timing.speech_end_to_release_ms is not None
        assert timing.source_to_release_ms is not None
        assert timing.pipeline_ms is not None
        assert timing.speech_end_to_release_ms == (
            timing.source_to_release_ms - timing.duration_ms
        )
        assert timing.speech_end_to_release_ms == (
            timing.decision_lag_ms + timing.pipeline_ms
        )


async def test_a_segment_that_failed_is_timed_too() -> None:
    """A rejection is a released segment; leaving it untimed would flatter the p95."""

    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now += 0.5
        if segment_index(request) == 0:
            return httpx.Response(500, json={"_result": {"status": "error"}})
        return ok("살아남은 문장")

    stream = stream_for(handler, clock)
    stream.push(TURN * 2)
    stream.close()
    utterances = await asyncio.wait_for(stream.drain(), timeout=5)

    assert len(utterances) == 1
    failed, kept = stream.timings
    assert failed.outcome == "REQUEST_FAILED"
    assert failed.utterance_id is None
    assert failed.released_at is not None
    assert failed.request_ms == 500
    assert kept.outcome == "RELEASED"
    assert kept.utterance_id == utterances[0].utterance_id


async def test_a_dropped_segment_never_claims_a_request_it_did_not_make() -> None:
    """No admission, no request: the timings say so instead of reading as zero."""

    clock = FakeClock()
    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return ok()

    stream = stream_for(handler, clock, max_concurrency=1, max_pending=1)
    stream.push(TURN * 4)
    stream.close()

    dropped = [t for t in stream.timings if t.outcome == "OVERLOADED"]
    assert len(dropped) == 3
    for timing in dropped:
        assert timing.admitted_at is None
        assert timing.queue_wait_ms is None
        assert timing.request_ms is None
        assert timing.proxy_display_lag_ms is None
        # It was still released, at the moment it was refused.
        assert timing.pipeline_ms == 0

    gate.set()
    await asyncio.wait_for(stream.drain(), timeout=5)


@pytest.mark.parametrize("stage", ["admitted_at", "request_started_at"])
async def test_a_stage_that_has_not_happened_reads_as_unknown(stage: str) -> None:
    """Never as zero: an absent measurement is not a fast one."""

    clock = FakeClock()
    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return ok()

    stream = stream_for(handler, clock, max_concurrency=1, max_pending=1)
    stream.push(TURN * 2)
    stream.close()

    refused = stream.timings[1]
    assert getattr(refused, stage) is None
    assert refused.head_of_line_wait_ms is None
    assert refused.source_to_release_ms is not None

    gate.set()
    await asyncio.wait_for(stream.drain(), timeout=5)


def test_the_segmentation_config_does_not_promise_a_display_number() -> None:
    """The docstring is the claim; it must not read as a measured one."""

    text = SegmentationConfig.__doc__ or ""
    assert "proxy" in text
    assert "browser" in text
