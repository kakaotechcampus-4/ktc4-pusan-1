"""The live path end to end: PCM in, utterances out, with the guards in place."""

import asyncio
import dataclasses
import gc
import io
import logging
import re
import wave

import httpx
import pytest

from audio import RATE, silence, tone
from irya_ai.schemas.transcript import PassType, SpeakerRole
from irya_ai.stt.elice import EliceSttClient
from irya_ai.stt.segmentation import CutReason
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
    assert utterance.seq >= 0
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
    assert [u.seq for u in utterances] == sorted(u.seq for u in utterances)
    assert len({u.seq for u in utterances}) == 3
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
    assert [r.reason for r in stream.rejected] == [
        "EMPTY",
        "TIMESTAMP_OVERRUN",
        "REQUEST_FAILED",
    ]


async def test_a_rejection_records_the_span_but_not_the_audio() -> None:
    """Rejections accumulate for a whole interview, so they must stay small.

    The span and the reason explain a gap in a transcript; the audio would only
    mean holding interview recordings in memory with no retention policy to
    hold them under.
    """

    stream = stream_for(lambda request: ok(""))
    stream.push(TURN)
    stream.close()

    assert await stream.drain() == []
    (rejected,) = stream.rejected
    assert rejected.reason == "EMPTY"
    assert rejected.cut_reason is CutReason.PAUSE
    assert rejected.end_ms > rejected.start_ms
    assert not any(
        isinstance(value, bytes | bytearray)
        for value in dataclasses.asdict(rejected).values()
    )


async def test_a_rejected_segment_does_not_disturb_the_order() -> None:
    """seq orders what the reader sees; it does not count what they see.

    It is derived from when audio was spoken, not from how many utterances
    came before, so dropping one leaves the rest in the same order rather than
    shifting them. The values are sparse by construction - see
    :mod:`irya_ai.stt.session` - and only their order is a contract.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if segment_index(request) == 0:
            return ok("")
        return ok("남은 발화")

    stream = stream_for(handler)
    stream.push(TURN * 3)
    stream.close()

    utterances = await stream.drain()
    kept = [u.seq for u in utterances]

    assert len(kept) == 2
    assert kept == sorted(kept)
    assert len(set(kept)) == 2
    assert all(seq >= 0 for seq in kept)
    # Order tracks spoken time, so the surviving pair keeps its spacing.
    assert (kept[1] > kept[0]) == (utterances[1].start_ms > utterances[0].start_ms)


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


# --- The producer/consumer lifecycle ----------------------------------------
#
# A live consumer starts before the audio does and keeps running through the
# pauses between turns. Every test here would have passed against a consumer
# that ends the moment the queue is momentarily empty, which is why they check
# what one consumer saw rather than what the stream eventually produced.


async def collect(stream: TranscriptionStream, expected: int) -> list:
    """Take ``expected`` utterances from one long-lived consumer."""

    seen = []
    async for utterance in stream:
        seen.append(utterance)
        if len(seen) == expected:
            break
    return seen


async def test_one_consumer_spans_the_gaps_between_turns() -> None:
    """The consumer starts before the audio and outlives the pauses in it.

    This is the shape of a live interview: iteration begins when the session
    does, the first turn arrives later, and the second arrives after a gap in
    which nothing is queued. A consumer that ends on an empty queue would stop
    before the first word, and the rest of the interview would only be visible
    to whoever started iterating next.
    """

    stream = stream_for(lambda request: ok("말했습니다"))
    seen = []

    async def consume() -> None:
        async for utterance in stream:
            seen.append(utterance.content)

    consumer = asyncio.ensure_future(consume())
    await asyncio.sleep(0)  # the consumer is now waiting on an empty open stream
    assert seen == []
    assert not consumer.done()

    stream.push(TURN)
    await asyncio.sleep(0.02)
    assert seen == ["말했습니다"]  # delivered without the stream being closed

    await asyncio.sleep(0.02)  # a gap: nothing queued, stream still open
    assert not consumer.done()

    stream.push(TURN)
    await asyncio.sleep(0.02)
    assert seen == ["말했습니다", "말했습니다"]

    stream.close()
    await asyncio.wait_for(consumer, timeout=2)


async def test_a_closed_stream_drains_then_ends() -> None:
    """Closing is not stopping: what is already queued still comes out."""

    released = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        await released.wait()
        return ok(f"문장 {segment_index(request)}")

    stream = stream_for(handler)
    stream.push(TURN * 3)
    stream.close()

    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0.02)
    assert not consumer.done()  # closed, but three requests are still out

    released.set()
    utterances = await asyncio.wait_for(consumer, timeout=2)

    assert [u.content for u in utterances] == ["문장 0", "문장 1", "문장 2"]


async def test_closing_an_empty_stream_ends_a_waiting_consumer() -> None:
    """A session that ends before anyone spoke still has to end."""

    stream = stream_for(lambda request: ok("네"))
    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0.01)
    assert not consumer.done()

    stream.close()

    assert await asyncio.wait_for(consumer, timeout=2) == []


async def test_the_tail_reaches_a_consumer_that_was_already_waiting() -> None:
    """The last answer has no trailing pause, so close() is what releases it."""

    stream = stream_for(lambda request: ok("마지막 문장입니다"))
    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0)

    assert stream.push(tone(2000)) == 0  # no pause yet, nothing to send
    await asyncio.sleep(0.01)
    assert not consumer.done()

    assert stream.close() == 1
    utterances = await asyncio.wait_for(consumer, timeout=2)

    assert [u.content for u in utterances] == ["마지막 문장입니다"]


async def test_a_failed_request_does_not_end_a_live_consumer() -> None:
    """One bad response is a gap in the transcript, not the end of it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if segment_index(request) == 0:
            return httpx.Response(500)
        return ok("이어서 계속합니다")

    stream = stream_for(handler)
    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0)

    stream.push(TURN)
    await asyncio.sleep(0.02)
    assert not consumer.done()

    stream.push(TURN)
    stream.close()
    utterances = await asyncio.wait_for(consumer, timeout=2)

    assert [u.content for u in utterances] == ["이어서 계속합니다"]
    assert [r.reason for r in stream.rejected] == ["REQUEST_FAILED"]


async def test_a_malformed_body_does_not_end_a_live_consumer() -> None:
    """A body the parser cannot read used to escape and kill the iteration.

    ``AttributeError`` and friends are not ``SttError``, so they went straight
    through the stream's handler and out of the ``async for``, taking every
    later segment with them.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if segment_index(request) == 0:
            return httpx.Response(200, text="<html>upstream unavailable</html>")
        if segment_index(request) == 1:
            return httpx.Response(200, json=[])
        return ok("그 다음 문장은 살아남습니다")

    stream = stream_for(handler)
    stream.push(TURN * 3)
    stream.close()

    utterances = await asyncio.wait_for(stream.drain(), timeout=2)

    assert [u.content for u in utterances] == ["그 다음 문장은 살아남습니다"]
    assert [r.reason for r in stream.rejected] == ["REQUEST_FAILED"] * 2
    assert [r.code for r in stream.rejected] == ["STT_MALFORMED_RESPONSE"] * 2


async def test_an_unbounded_integer_timestamp_does_not_end_a_live_consumer() -> None:
    """``OverflowError`` is not ``SttError`` either, so it escaped the same way.

    A JSON integer has no upper bound. Four spans that are each too large in
    magnitude to become a float, then a good one, to show the arithmetic is
    refused at the boundary rather than raised past it.
    """

    huge = [
        [0, 10**400],
        [10**400, 1],
        [0, -(10**400)],
        [-(10**400), 1],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        index = segment_index(request)
        if index < len(huge):
            return httpx.Response(
                200,
                json={
                    "transcript": {
                        "text": "값이 너무 큽니다",
                        "chunks": [{"timestamp": huge[index]}],
                    }
                },
            )
        return ok("그 다음 문장은 살아남습니다")

    stream = stream_for(handler)
    stream.push(TURN * (len(huge) + 1))
    stream.close()

    utterances = await asyncio.wait_for(stream.drain(), timeout=2)

    assert [u.content for u in utterances] == ["그 다음 문장은 살아남습니다"]
    assert [r.code for r in stream.rejected] == ["STT_MALFORMED_RESPONSE"] * len(huge)


async def test_a_second_consumer_advancing_the_queue_is_refused() -> None:
    """Two at once would split the order between them, so the second raises."""

    released = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        await released.wait()
        return ok("네")

    stream = stream_for(handler)
    stream.push(TURN)
    stream.close()

    first = aiter(stream)
    taken = asyncio.ensure_future(anext(first))
    # Let it reach the response it is waiting on, which is where a second
    # consumer would start reading the same segment.
    await asyncio.sleep(0.01)
    assert not taken.done()

    with pytest.raises(RuntimeError, match="one consumer"):
        await anext(aiter(stream))

    released.set()
    assert (await asyncio.wait_for(taken, timeout=2)).content == "네"
    await first.aclose()


async def test_breaking_out_of_the_loop_does_not_lock_the_stream() -> None:
    """A consumer that stops early leaves the stream usable by the next one."""

    stream = stream_for(lambda request: ok("네"))
    stream.push(TURN)
    stream.push(TURN)
    stream.close()

    first = await asyncio.wait_for(collect(stream, 1), timeout=2)
    assert len(first) == 1

    # No aclose, no gc: the abandoned generator is still parked at its yield.
    rest = await asyncio.wait_for(stream.drain(), timeout=2)
    assert len(rest) == 1


async def test_a_cancelled_consumer_leaves_the_queue_for_the_next_one() -> None:
    """Cancelling mid-response must not silently eat the response."""

    released = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        await released.wait()
        return ok("기다리던 문장")

    stream = stream_for(handler)
    stream.push(TURN)
    stream.close()

    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0.01)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

    released.set()
    utterances = await asyncio.wait_for(stream.drain(), timeout=2)

    assert [u.content for u in utterances] == ["기다리던 문장"]


async def test_closing_under_a_consumer_ends_it_instead_of_cancelling_it() -> None:
    """Abandoning the stream is the stream's end, not the consumer's failure.

    The consumer is parked on a request that ``aclose`` then cancels. It has
    to come back with what it had and stop, because a ``CancelledError``
    surfacing here would look to the caller's supervisor like the consuming
    task itself was cancelled - and a caller that does not re-raise it turns
    into a task that swallowed a cancellation.
    """

    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if segment_index(request) > 0:
            await gate.wait()
        return ok("첫 문장")

    stream = stream_for(handler, max_concurrency=2)
    stream.push(TURN * 2)

    consumer = asyncio.ensure_future(stream.drain())
    # Far enough in to have delivered the first and be waiting on the second.
    await asyncio.sleep(0.05)
    assert not consumer.done()

    await asyncio.wait_for(stream.aclose(), timeout=2)

    utterances = await asyncio.wait_for(consumer, timeout=2)
    assert [u.content for u in utterances] == ["첫 문장"]
    assert stream.pending == 0
    assert [t.outcome for t in stream.timings] == ["RELEASED", "ABANDONED"]


async def test_an_abandoned_segment_is_not_counted_twice() -> None:
    """``aclose`` already recorded it; resolving it again must not re-report."""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return ok("도달하지 않음")

    stream = stream_for(handler)
    stream.push(TURN)

    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0.05)
    await asyncio.wait_for(stream.aclose(), timeout=2)

    assert await asyncio.wait_for(consumer, timeout=2) == []
    # Abandoning is not a rejected span: no text was ever going to arrive and
    # the caller asked for that. It is in the timings, once.
    assert stream.dropped_spans == []
    assert [t.outcome for t in stream.timings] == ["ABANDONED"]


async def abandon_when_the_request_lands(response: httpx.Response):
    """A stream abandoned in the same iteration its request comes back.

    The narrow interleaving: the provider answers, and before the waiting
    consumer is resumed, something else calls ``aclose``. Cancelling a task
    that has already finished does nothing, so the consumer wakes with a real
    result rather than a ``CancelledError`` - for a segment the stream has
    just disowned. Driven from a done callback because that is the one place
    guaranteed to run between the task finishing and its waiter resuming.
    """

    started, finish = asyncio.Event(), asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await finish.wait()
        return response

    stream = stream_for(handler)
    stream.push(TURN)
    await asyncio.wait_for(started.wait(), timeout=2)

    closing: list[asyncio.Future] = []
    stream._pending[0].task.add_done_callback(
        lambda task: closing.append(asyncio.ensure_future(stream.aclose()))
    )
    consumer = asyncio.ensure_future(stream.drain())
    await asyncio.sleep(0)
    finish.set()

    utterances = await asyncio.wait_for(consumer, timeout=2)
    await asyncio.wait_for(asyncio.gather(*closing), timeout=2)
    return stream, utterances


async def test_a_result_arriving_as_the_stream_is_abandoned_is_not_emitted() -> None:
    stream, utterances = await abandon_when_the_request_lands(ok("버려진 뒤 도착"))

    assert utterances == []
    # Abandoned is terminal: the success must not overwrite it to RELEASED.
    assert [t.outcome for t in stream.timings] == ["ABANDONED"]
    assert stream.timings[0].utterance_id is None
    assert stream.rejected == []
    assert stream.pending == 0


async def test_a_failure_arriving_as_the_stream_is_abandoned_is_not_reported() -> None:
    stream, utterances = await abandon_when_the_request_lands(
        httpx.Response(500, text="upstream unavailable")
    )

    assert utterances == []
    # The same segment must not be recorded as abandoned and then rejected.
    assert [t.outcome for t in stream.timings] == ["ABANDONED"]
    assert stream.rejected == []
    assert stream.pending == 0


async def test_abandoning_after_a_normal_drain_keeps_the_released_outcome() -> None:
    """``aclose`` after the work is done must not rewrite finished metrics."""

    stream = stream_for(lambda request: ok("정상 종료"))
    stream.push(TURN)
    stream.close()

    utterances = await asyncio.wait_for(stream.drain(), timeout=2)
    assert [u.content for u in utterances] == ["정상 종료"]
    await asyncio.wait_for(stream.aclose(), timeout=2)

    assert [t.outcome for t in stream.timings] == ["RELEASED"]
    assert stream.rejected == []


async def test_aclose_cancels_what_is_in_flight_and_leaves_nothing_behind() -> None:
    """Giving up early must not leave requests running or tasks uncollected."""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return ok("도달하지 않음")

    stream = stream_for(handler)
    stream.push(TURN * 2)
    assert stream.pending == 2
    tasks = [work.task for work in stream._pending]

    await asyncio.wait_for(stream.aclose(), timeout=2)

    assert stream.pending == 0
    assert all(task.done() for task in tasks)
    assert all(task.cancelled() for task in tasks)
    assert await asyncio.wait_for(stream.drain(), timeout=2) == []


async def test_an_abandoned_failing_request_is_never_reported_by_asyncio() -> None:
    """asyncio prints an uncollected task's traceback, and it holds the URL.

    The message is "Task exception was never retrieved", it is written by
    asyncio's own handler rather than this module's logger, and the traceback
    in it runs through ``httpx`` frames carrying the deployment address. So
    the check is at the root logger and at the loop's exception handler, not
    at ``irya_ai.stt.stream``.
    """

    canary = "SYNTHETIC-PRIVATE-DEPLOYMENT-HOST"
    reported: list[dict] = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context))

    records = logging.StreamHandler(io.StringIO())
    root = logging.getLogger()
    root.addHandler(records)
    try:
        client = EliceSttClient(
            httpx.AsyncClient(
                base_url=f"https://{canary}.invalid",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(500, text=canary)
                ),
            ),
            retries=0,
            backoff_seconds=0.0,
        )
        stream = TranscriptionStream(
            client,
            session_id="ses_test",
            track_id="trk_candidate",
            speaker=SpeakerRole.CANDIDATE,
        )
        stream.push(TURN)
        await asyncio.sleep(0.02)  # the request fails while nobody is consuming
        await stream.aclose()
        del stream
        gc.collect()
        await asyncio.sleep(0)
    finally:
        root.removeHandler(records)
        loop.set_exception_handler(previous)

    assert reported == []
    assert canary not in records.stream.getvalue()


async def test_a_failed_segment_logs_its_code_and_nothing_from_the_provider() -> None:
    """The ordinary failure path: what it says, and what it must never say.

    Canaries sit in the response body, in the deployment host and in the
    exception chain behind the error. The handler formats exceptions as well
    as messages, so an ``exc_info`` added here later - the natural thing to
    reach for while debugging - fails this test rather than shipping the URL
    into the log.
    """

    body = "SYNTHETIC-PROVIDER-BODY-CANARY"
    host = "SYNTHETIC-PRIVATE-HOST-CANARY"
    chained = "SYNTHETIC-EXCEPTION-CHAIN-CANARY"

    def handler(request: httpx.Request) -> httpx.Response:
        # Two failure shapes, because they reach the log by different routes:
        # a status error carrying the body, and a transport error carrying a
        # chain. Both end as the same code.
        if segment_index(request) == 0:
            return httpx.Response(500, text=body)
        try:
            raise ValueError(chained)
        except ValueError as exc:
            raise httpx.ConnectError(f"{chained} at {host}") from exc

    records = logging.StreamHandler(io.StringIO())
    records.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log = logging.getLogger("irya_ai.stt.stream")
    log.addHandler(records)
    previous = log.level
    log.setLevel(logging.DEBUG)
    try:
        client = EliceSttClient(
            httpx.AsyncClient(
                base_url=f"https://{host}.invalid",
                transport=httpx.MockTransport(handler),
            ),
            retries=0,
            backoff_seconds=0.0,
        )
        stream = TranscriptionStream(
            client,
            session_id="ses_test",
            track_id="trk_candidate",
            speaker=SpeakerRole.CANDIDATE,
        )
        stream.push(TURN * 2)
        stream.close()
        assert await asyncio.wait_for(stream.drain(), timeout=2) == []
    finally:
        log.removeHandler(records)
        log.setLevel(previous)

    written = records.stream.getvalue()
    # The stable code is the point of the log line; without it the rest is
    # just a silence that happens to be safe.
    assert written.count("STT_REQUEST_FAILED") == 2
    assert "segment 0" in written
    assert "segment 1" in written
    for canary in (body, host, chained):
        assert canary not in written


async def test_a_dropped_transcript_is_never_quoted_into_the_log() -> None:
    """Rejections name the reason and the span, never what was said."""

    spoken = "합격자만 아는 문장입니다"

    records = logging.StreamHandler(io.StringIO())
    log = logging.getLogger("irya_ai.stt.stream")
    log.addHandler(records)
    previous = log.level
    log.setLevel(logging.DEBUG)
    try:
        # A span running far past the audio: the text comes back and is
        # dropped, which is exactly when quoting it would be tempting.
        stream = stream_for(lambda request: ok(spoken, end_s=90.0))
        stream.push(TURN)
        stream.close()
        assert await asyncio.wait_for(stream.drain(), timeout=2) == []
    finally:
        log.removeHandler(records)
        log.setLevel(previous)

    written = records.stream.getvalue()
    assert "TIMESTAMP_OVERRUN" in written
    assert spoken not in written


# --- Bounded queueing -------------------------------------------------------


async def test_a_producer_faster_than_the_deployment_does_not_grow_forever() -> None:
    """Audio is live, so the backlog is what has to give, not the producer.

    Before there was a budget, every pushed segment scheduled a task holding
    its PCM whether or not a request could progress: a blocked deployment and
    thirty turns retained every byte of all thirty.
    """

    gate = asyncio.Event()
    started = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal started
        started += 1
        await gate.wait()
        return ok("네")

    stream = stream_for(handler, max_concurrency=1, max_pending=4)
    accepted = 0
    for _ in range(30):
        accepted += stream.push(TURN)
        await asyncio.sleep(0)

    assert stream.pending == 4  # the budget, not the 30 that were pushed
    assert accepted == 4
    assert stream.overloaded
    assert len(stream.dropped_spans) == 26
    assert started == 1  # one request is in flight; the rest never started

    # The dropped spans say exactly which audio has no transcript, and hold
    # none of it.
    dropped = stream.dropped_spans[0]
    assert dropped.end_ms > dropped.start_ms
    assert dropped.code is None
    assert not any(
        isinstance(value, bytes | bytearray)
        for value in dataclasses.asdict(dropped).values()
    )

    gate.set()
    stream.close()
    await asyncio.wait_for(stream.drain(), timeout=2)


async def test_admission_recovers_once_the_backlog_clears() -> None:
    """Overload is a moment, not a state the stream stays stuck in."""

    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return ok("네")

    stream = stream_for(handler, max_concurrency=1, max_pending=2)
    consumer = asyncio.ensure_future(collect(stream, expected=2))

    for _ in range(4):
        stream.push(TURN)
        await asyncio.sleep(0)
    assert len(stream.dropped_spans) == 2

    gate.set()
    await asyncio.wait_for(consumer, timeout=2)
    assert stream.pending == 0

    assert stream.push(TURN) == 1  # room again, and it is taken
    assert len(stream.dropped_spans) == 2

    stream.close()
    await asyncio.wait_for(stream.drain(), timeout=2)


async def test_dropping_for_overload_never_blocks_the_producer() -> None:
    """push() is on the media path and may not await anything."""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return ok("네")

    stream = stream_for(handler, max_concurrency=1, max_pending=1)
    stream.push(TURN)

    # No await between these: if push() could block, this would not finish.
    for _ in range(10):
        stream.push(TURN)

    assert stream.pending == 1
    assert len(stream.dropped_spans) == 10
    await asyncio.wait_for(stream.aclose(), timeout=2)


async def test_a_dropped_segment_keeps_the_order_of_what_survived() -> None:
    """A hole in the transcript must not reorder the text around it."""

    stream = stream_for(lambda request: ok("살아남은 문장"), max_pending=2)
    stream.push(TURN * 5)
    stream.close()

    utterances = await asyncio.wait_for(stream.drain(), timeout=2)
    seqs = [u.seq for u in utterances]

    assert len(utterances) == 2
    assert seqs == sorted(seqs)
    assert [u.start_ms for u in utterances] == sorted(u.start_ms for u in utterances)
    assert len(stream.dropped_spans) == 3


def test_a_stream_refuses_a_budget_that_cannot_hold_anything() -> None:
    with pytest.raises(ValueError, match="max_pending"):
        stream_for(lambda request: ok("네"), max_pending=0)


@pytest.mark.parametrize("limit", [0, -1])
def test_a_stream_refuses_a_concurrency_that_would_never_send(limit: int) -> None:
    """``Semaphore(0)`` grants no slot ever, so the refusal has to be loud.

    Accepting it would hand back a stream that takes audio, queues it, and
    transcribes none of it - an interview that looks live and produces
    nothing, with no error anywhere to say why.
    """

    with pytest.raises(ValueError, match="max_concurrency"):
        stream_for(lambda request: ok("네"), max_concurrency=limit)


@pytest.mark.parametrize("field", ["session_id", "track_id"])
def test_a_stream_refuses_an_utterance_it_could_not_attribute(field: str) -> None:
    """Every utterance carries these; an empty one is an unowned transcript."""

    identity = {"session_id": "ses_test", "track_id": "trk_candidate", field: ""}
    client = EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid",
            transport=httpx.MockTransport(lambda request: ok("네")),
        )
    )

    with pytest.raises(ValueError, match=field):
        TranscriptionStream(client, speaker=SpeakerRole.CANDIDATE, **identity)


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
