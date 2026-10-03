"""The fan-out: every sink gets every utterance, and one failure stays one failure."""

import asyncio
import logging

import pytest

from irya_ai.schemas.transcript import SpeakerRole, Utterance
from irya_ai.sinks import FanOutSink, sink_name


def utterance(n: int = 0, **overrides) -> Utterance:
    fields = {
        "utterance_id": f"utt_track_{n:04d}",
        "session_id": "ses_123",
        "track_id": "track",
        "speaker": SpeakerRole.CANDIDATE,
        "seq": n,
        "start_ms": 1000 * n,
        "end_ms": 1000 * n + 900,
        "content": f"발화 {n}",
    }
    return Utterance(**{**fields, **overrides})


class Recorder:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def __call__(self, value: Utterance) -> None:
        self.seen.append(value.utterance_id)


async def test_every_sink_receives_every_utterance_in_order() -> None:
    first, second = Recorder(), Recorder()
    order: list[str] = []

    async def tag_first(value: Utterance) -> None:
        order.append("first")
        await first(value)

    async def tag_second(value: Utterance) -> None:
        order.append("second")
        await second(value)

    fan_out = FanOutSink([tag_first, tag_second])
    for n in range(3):
        await fan_out(utterance(n))

    expected = ["utt_track_0000", "utt_track_0001", "utt_track_0002"]
    assert first.seen == second.seen == expected
    assert order == ["first", "second"] * 3, "sinks run one after the other, in order"
    assert not fan_out.failures


async def test_a_raising_sink_does_not_stop_the_others(caplog) -> None:
    before, after = Recorder(), Recorder()

    async def broken(_value: Utterance) -> None:
        raise ConnectionError("room went away")

    fan_out = FanOutSink([before, broken, after])
    with caplog.at_level(logging.WARNING, logger="irya_ai.sinks"):
        await fan_out(utterance(0))
        await fan_out(utterance(1))

    # The call returned normally both times and the sinks around the broken
    # one saw both utterances - the failure cost exactly one sink's delivery.
    assert before.seen == after.seen == ["utt_track_0000", "utt_track_0001"]
    assert fan_out.failures == {"broken": 2}

    # A traceback once, then one line per failure: a sink that is down for
    # the whole interview must not fill the log with the same stack.
    records = [r for r in caplog.records if r.name == "irya_ai.sinks"]
    assert [r.exc_info is not None for r in records] == [True, False]
    assert all("발화" not in r.getMessage() for r in records), "never the text"


async def test_the_next_utterance_is_offered_to_a_sink_that_failed() -> None:
    calls = 0

    async def flaky(_value: Utterance) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("first send timed out")

    fan_out = FanOutSink([flaky])
    await fan_out(utterance(0))
    await fan_out(utterance(1))

    assert calls == 2, "a failure is per utterance, not a switch-off"
    assert fan_out.failures == {"flaky": 1}


async def test_cancellation_passes_through_untouched() -> None:
    reached_after: list[str] = []

    async def blocks(_value: Utterance) -> None:
        await asyncio.sleep(60)

    async def after(value: Utterance) -> None:
        reached_after.append(value.utterance_id)

    fan_out = FanOutSink([blocks, after])
    task = asyncio.create_task(fan_out(utterance(0)))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert reached_after == [], "a cancel stops the fan-out; it is not a sink failure"
    assert not fan_out.failures


def test_sink_names_come_from_functions_and_classes() -> None:
    async def named(_value: Utterance) -> None:
        pass

    assert sink_name(named) == "named"
    assert sink_name(Recorder()) == "Recorder"
