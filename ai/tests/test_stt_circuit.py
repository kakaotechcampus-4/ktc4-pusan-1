"""The STT circuit breaker: on its own, in the client, and under the stream."""

import asyncio

import httpx
import pytest

from audio import silence, tone
from irya_ai.schemas.transcript import SpeakerRole
from irya_ai.stt.circuit import Admission, CircuitBreaker
from irya_ai.stt.elice import EliceSttClient, SttError
from irya_ai.stt.stream import TranscriptionStream

TURN = tone(1500) + silence(800)
WAV = b"RIFF-not-really-a-wav"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def ok(text: str = "네") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "text": text,
            "segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": text}],
        },
    )


def breaker_for(clock: Clock, changes: list[bool] | None = None, **kwargs):
    return CircuitBreaker(
        clock=clock,
        on_state_change=None if changes is None else changes.append,
        **kwargs,
    )


def client_for(handler, breaker: CircuitBreaker, **kwargs) -> EliceSttClient:
    return EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid", transport=httpx.MockTransport(handler)
        ),
        backoff_seconds=0.0,
        breaker=breaker,
        **kwargs,
    )


# --- The breaker on its own -------------------------------------------------


def test_it_opens_on_the_threshold_and_not_before() -> None:
    clock, changes = Clock(), []
    breaker = breaker_for(clock, changes, failure_threshold=3)

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.admit() is Admission.SEND

    breaker.record_failure()
    assert breaker.is_open
    assert breaker.admit() is Admission.REFUSE
    assert changes == [True]


def test_a_success_in_between_resets_the_count() -> None:
    breaker = breaker_for(Clock(), failure_threshold=3)

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()

    assert not breaker.is_open


def test_a_trip_opens_it_on_one_failure() -> None:
    breaker = breaker_for(Clock(), failure_threshold=3)

    breaker.record_failure(trip=True)

    assert breaker.is_open


def test_after_the_cooldown_exactly_one_probe_is_admitted() -> None:
    clock = Clock()
    breaker = breaker_for(clock, failure_threshold=1, cooldown_seconds=5.0)
    breaker.record_failure()

    clock.now += 4.9
    assert breaker.admit() is Admission.REFUSE
    clock.now += 0.1
    assert [breaker.admit() for _ in range(3)] == [
        Admission.PROBE,
        Admission.REFUSE,
        Admission.REFUSE,
    ]


def test_a_failed_probe_restarts_the_cooldown() -> None:
    clock = Clock()
    breaker = breaker_for(clock, failure_threshold=1, cooldown_seconds=5.0)
    breaker.record_failure()
    clock.now += 5.0
    assert breaker.admit() is Admission.PROBE

    clock.now += 3.0  # the probe itself took a while to fail
    breaker.record_failure()

    clock.now += 4.9
    assert breaker.admit() is Admission.REFUSE
    clock.now += 0.1
    assert breaker.admit() is Admission.PROBE


def test_a_released_probe_frees_the_slot_without_a_verdict() -> None:
    clock = Clock()
    breaker = breaker_for(clock, failure_threshold=1, cooldown_seconds=5.0)
    breaker.record_failure()
    clock.now += 5.0
    assert breaker.admit() is Admission.PROBE

    breaker.release_probe()

    assert breaker.is_open
    assert breaker.admit() is Admission.PROBE


def test_each_transition_is_announced_once() -> None:
    clock, changes = Clock(), []
    breaker = breaker_for(clock, changes, failure_threshold=1)

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_success()

    assert changes == [True, False]


def test_a_listener_that_raises_does_not_reach_the_caller(caplog) -> None:
    def broken(_opened: bool) -> None:
        raise RuntimeError("listener bug")

    breaker = CircuitBreaker(failure_threshold=1, on_state_change=broken)

    breaker.record_failure()
    breaker.record_success()

    assert "listener raised" in caplog.text


@pytest.mark.parametrize("kwargs", [{"failure_threshold": 0}, {"cooldown_seconds": 0}])
def test_it_refuses_settings_that_could_never_work(kwargs) -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(**kwargs)


# --- In the client ----------------------------------------------------------


async def test_failing_calls_open_it_and_then_nothing_is_sent() -> None:
    """500 then 200: one degraded, no requests while open, one recovered."""

    clock, changes = Clock(), []
    sent = 0
    healthy = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return ok() if healthy else httpx.Response(500)

    client = client_for(handler, breaker_for(clock, changes), retries=2)

    for _ in range(3):
        with pytest.raises(SttError, match="STT_REQUEST_FAILED"):
            await client.transcribe(WAV)
    # Per call, not per attempt: three calls of three attempts each.
    assert sent == 9
    assert changes == [True]

    for _ in range(5):
        with pytest.raises(SttError) as caught:
            await client.transcribe(WAV)
        assert caught.value.code == "STT_CIRCUIT_OPEN"
        assert caught.value.retryable
    assert sent == 9

    healthy = True
    clock.now += 5.0
    assert (await client.transcribe(WAV)).text == "네"
    assert (await client.transcribe(WAV)).text == "네"
    assert sent == 11
    assert changes == [True, False]


async def test_a_probe_asks_once_and_does_not_retry() -> None:
    clock = Clock()
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(503)

    client = client_for(handler, breaker_for(clock, failure_threshold=1), retries=2)
    with pytest.raises(SttError):
        await client.transcribe(WAV)
    assert sent == 3

    clock.now += 5.0
    with pytest.raises(SttError, match="STT_REQUEST_FAILED"):
        await client.transcribe(WAV)
    assert sent == 4


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (httpx.Response(503), "STT_REQUEST_FAILED"),
        (httpx.Response(401), "STT_AUTH_FAILED"),
        (
            httpx.Response(200, text="<html>Bad Gateway</html>"),
            "STT_MALFORMED_RESPONSE",
        ),
    ],
)
async def test_a_failed_probe_allows_another_probe_after_the_cooldown(
    failure: httpx.Response, code: str
) -> None:
    clock, changes = Clock(), []
    replies = iter([failure, failure, ok(), ok()])
    client = client_for(
        lambda request: next(replies),
        breaker_for(clock, changes, failure_threshold=1),
        retries=0,
    )
    try:
        with pytest.raises(SttError, match=code):
            await client.transcribe(WAV)
        clock.now += 5.0
        with pytest.raises(SttError, match=code):
            await client.transcribe(WAV)
        with pytest.raises(SttError, match="STT_CIRCUIT_OPEN"):
            await client.transcribe(WAV)

        clock.now += 5.0
        assert (await client.transcribe(WAV)).text == "네"
        assert (await client.transcribe(WAV)).text == "네"
        assert not client.breaker.is_open
        assert changes == [True, False]
    finally:
        await client.client.aclose()


async def test_a_rejected_key_opens_it_at_once() -> None:
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(401)

    client = client_for(handler, breaker_for(Clock()), retries=2)

    with pytest.raises(SttError, match="STT_AUTH_FAILED"):
        await client.transcribe(WAV)
    with pytest.raises(SttError, match="STT_CIRCUIT_OPEN"):
        await client.transcribe(WAV)
    assert sent == 1


async def test_a_gateway_error_page_counts_as_a_failure() -> None:
    client = client_for(
        lambda request: httpx.Response(200, text="<html>Bad Gateway</html>"),
        breaker_for(Clock()),
    )

    for _ in range(3):
        with pytest.raises(SttError, match="STT_MALFORMED_RESPONSE"):
            await client.transcribe(WAV)

    assert client.breaker.is_open


async def test_a_request_this_client_got_wrong_does_not_count() -> None:
    """A 4xx is about the request; the deployment answered it."""

    client = client_for(lambda request: httpx.Response(413), breaker_for(Clock()))

    for _ in range(5):
        with pytest.raises(SttError, match="STT_CLIENT_ERROR"):
            await client.transcribe(WAV)

    assert not client.breaker.is_open


async def test_an_empty_transcription_is_a_success() -> None:
    clock = Clock()
    replies = iter([httpx.Response(500), ok(""), httpx.Response(500)])
    client = client_for(
        lambda request: next(replies),
        breaker_for(clock, failure_threshold=2),
        retries=0,
    )

    with pytest.raises(SttError):
        await client.transcribe(WAV)
    assert (await client.transcribe(WAV)).is_empty
    with pytest.raises(SttError):
        await client.transcribe(WAV)

    assert not client.breaker.is_open


async def test_half_open_lets_exactly_one_of_many_concurrent_calls_through() -> None:
    """One client per room, several tracks on it: the probe is single-flight."""

    clock = Clock()
    sent = 0
    answer = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        await answer.wait()
        return ok()

    breaker = breaker_for(clock, failure_threshold=1)
    breaker.record_failure()
    clock.now += 5.0
    client = client_for(handler, breaker)

    calls = [asyncio.ensure_future(client.transcribe(WAV)) for _ in range(6)]
    await asyncio.sleep(0.01)
    answer.set()
    results = await asyncio.gather(*calls, return_exceptions=True)

    assert sent == 1
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert {r.code for r in results if isinstance(r, SttError)} == {"STT_CIRCUIT_OPEN"}
    assert not breaker.is_open


async def test_a_cancelled_probe_gives_the_slot_back() -> None:
    """Otherwise one cancel leaves the breaker refusing every call for good."""

    clock = Clock()
    hang = True

    async def handler(request: httpx.Request) -> httpx.Response:
        if hang:
            await asyncio.Event().wait()
        return ok()

    breaker = breaker_for(clock, failure_threshold=1)
    breaker.record_failure()
    clock.now += 5.0
    client = client_for(handler, breaker)

    probe = asyncio.ensure_future(client.transcribe(WAV))
    await asyncio.sleep(0.01)
    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe

    hang = False
    assert (await client.transcribe(WAV)).text == "네"
    assert not breaker.is_open


async def test_a_call_already_retrying_stops_once_another_opens_it() -> None:
    breaker = breaker_for(Clock())
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        if sent == 2:
            # Another track's call is rejected outright meanwhile.
            breaker.record_failure(trip=True)
        return httpx.Response(500)

    client = client_for(handler, breaker, retries=5)

    with pytest.raises(SttError, match="STT_REQUEST_FAILED"):
        await client.transcribe(WAV)

    # Not the six attempts it would otherwise spend.
    assert sent == 2


async def test_a_failed_warm_up_does_not_count_towards_opening() -> None:
    """A scale-to-zero deployment failing its warm-up is expected."""

    client = client_for(
        lambda request: httpx.Response(503),
        breaker_for(Clock(), failure_threshold=1),
        retries=0,
    )

    assert await client.warm_up(WAV) is False
    assert not client.breaker.is_open


async def test_without_a_breaker_nothing_changes() -> None:
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(500)

    client = EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid", transport=httpx.MockTransport(handler)
        ),
        retries=0,
        backoff_seconds=0.0,
    )
    for _ in range(10):
        with pytest.raises(SttError, match="STT_REQUEST_FAILED"):
            await client.transcribe(WAV)
    assert sent == 10


# --- Under the stream: the outage actually seen ------------------------------


async def test_a_deployment_that_never_answers_opens_it_through_the_deadline() -> None:
    """Accepts the connection, never answers: the client only sees a cancel.

    The stream's deadline is what notices, so the stream is what has to tell
    the breaker. Once it is open, later segments are refused at once with
    nothing sent, and when the deployment comes back a probe finds it and
    captions resume.
    """

    clock, changes = Clock(), []
    sent = 0
    answering = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        await answering.wait()
        return ok("돌아왔습니다")

    client = client_for(handler, breaker_for(clock, changes), retries=0)
    stream = TranscriptionStream(
        client,
        session_id="ses_test",
        track_id="trk_candidate",
        speaker=SpeakerRole.CANDIDATE,
        request_deadline_seconds=0.05,
    )
    utterances = []

    async def consume() -> None:
        async for utterance in stream:
            utterances.append(utterance)

    consumer = asyncio.ensure_future(consume())

    stream.push(TURN * 3)
    await asyncio.sleep(0.2)
    assert sent == 3
    assert changes == [True]

    stream.push(TURN * 3)
    await asyncio.sleep(0.05)
    assert sent == 3  # refused without sending, not held for the deadline

    answering.set()
    clock.now += 5.0
    stream.push(TURN * 2)
    stream.close()
    await asyncio.wait_for(consumer, timeout=2)

    assert [r.code for r in stream.rejected] == [
        "STT_DEADLINE_EXCEEDED",
        "STT_DEADLINE_EXCEEDED",
        "STT_DEADLINE_EXCEEDED",
        "STT_CIRCUIT_OPEN",
        "STT_CIRCUIT_OPEN",
        "STT_CIRCUIT_OPEN",
    ]
    assert [u.content for u in utterances] == ["돌아왔습니다", "돌아왔습니다"]
    assert sent == 5
    assert changes == [True, False]


async def test_closing_the_stream_does_not_count_against_the_deployment() -> None:
    """A cancel from ``aclose`` is not a deadline and is not a failure."""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        return ok()

    client = client_for(handler, breaker_for(Clock(), failure_threshold=1))
    stream = TranscriptionStream(
        client,
        session_id="ses_test",
        track_id="trk_candidate",
        speaker=SpeakerRole.CANDIDATE,
    )
    stream.push(TURN * 3)
    await asyncio.sleep(0.02)
    await stream.aclose()

    assert not client.breaker.is_open
