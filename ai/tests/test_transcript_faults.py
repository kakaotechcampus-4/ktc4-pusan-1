"""Fault injection on the Backend transcript WebSocket.

A scripted ``aiohttp`` peer on 127.0.0.1 plays the Backend: it can refuse,
stall the upgrade, close with any code, answer out of order, answer with
garbage, or answer slowly. Captions sit beside the transcript runner in a
``FanOutSink`` exactly as in the worker, so every test also checks that the
Backend's trouble never reaches the caption path, and that what the Backend
does store is every utterance exactly once by id.

``tests/test_transcripts.py`` covers the channel's own rules against a fake
peer; these cover the channel, the runner and the fan-out together.
"""

import asyncio
import contextlib
import json
import logging
import socket
import time
from collections.abc import Awaitable, Callable

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from irya_ai.schemas.transcript import Utterance
from irya_ai.sinks import FanOutSink
from irya_ai.stt.http_logging import clear_protected_hosts
from irya_ai.transcript_runner import TranscriptRunner
from irya_ai.transcripts import FRAME_ACK, TranscriptChannel, transcript_url

pytestmark = pytest.mark.asyncio

SECRET = "SENTINEL-면접-발화-5521"
BOUND = 3.0

Script = Callable[[int, dict, web.WebSocketResponse], Awaitable[bool | None]]


@pytest.fixture(autouse=True)
def _forget_protected_hosts():
    clear_protected_hosts()
    yield
    clear_protected_hosts()


def utterance(index: int = 0, **changes) -> Utterance:
    return Utterance.model_validate(
        {
            "utteranceId": f"utt_{index}",
            "sessionId": "ses_123",
            "trackId": "TR_candidate",
            "speaker": "CANDIDATE",
            "seq": index,
            "startMs": index * 1000,
            "endMs": index * 1000 + 500,
            "content": f"{SECRET} {index}",
            **changes,
        }
    )


async def ack(connection: int, frame: dict, ws: web.WebSocketResponse) -> None:
    await ws.send_str(json.dumps({"type": FRAME_ACK, "utteranceId": frame["id"]}))


class Backend:
    """A transcript peer whose every answer is a script.

    ``script(connection, frame, ws)`` decides what each frame gets; returning
    ``True`` ends that connection. ``stall_first`` leaves the first upgrade
    unanswered for good - a Backend (or proxy) that accepted the TCP
    connection and then never spoke. ``stored`` is what an ACK'ing Backend
    would hold: ids, deduplicated the way the real upsert deduplicates them.
    """

    def __init__(self, script: Script = ack, *, stall_first: bool = False) -> None:
        self.script = script
        self.stall_first = stall_first
        self.handshakes = 0
        self.connections = 0
        self.frames: list[tuple[int, str]] = []
        self.stored: dict[str, int] = {}
        self._never = asyncio.Event()
        self._server: TestServer | None = None

    async def __aenter__(self) -> "Backend":
        app = web.Application()
        app.router.add_get("/internal/v1/sessions/{sid}/transcripts", self._handle)
        self._server = TestServer(app)
        await self._server.start_server()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        assert self._server is not None
        self._never.set()
        await asyncio.wait_for(self._server.close(), BOUND)

    def url(self) -> str:
        assert self._server is not None
        base = str(self._server.make_url("")).rstrip("/")
        return transcript_url(base, "ses_123")

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        self.handshakes += 1
        if self.stall_first and self.handshakes == 1:
            await self._never.wait()
            return web.Response(status=503)
        self.connections += 1
        connection = self.connections
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for message in ws:
            if message.type is not aiohttp.WSMsgType.TEXT:
                continue
            frame = json.loads(message.data)
            frame["id"] = frame["utteranceId"]
            self.frames.append((connection, frame["id"]))
            if await self.script(connection, frame, ws):
                break
        return ws


def channel_for(backend: Backend, **kwargs) -> TranscriptChannel:
    kwargs.setdefault("reconnect_backoff_seconds", 0.0)
    kwargs.setdefault("ack_timeout_seconds", 0.5)
    return TranscriptChannel(
        backend.url(), headers={"Authorization": "Bearer unit-test-token"}, **kwargs
    )


class Pipeline:
    """Captions and the transcript runner side by side, as the worker wires them."""

    def __init__(self, channel: TranscriptChannel, max_queue: int = 200) -> None:
        self.captions: list[str] = []
        self.runner = TranscriptRunner(
            channel, session_id="ses_123", max_queue=max_queue
        )
        self.runner.start()

        async def caption(u: Utterance) -> None:
            self.captions.append(u.utterance_id)

        self.sink = FanOutSink([caption, self.runner])

    async def speak(self, count: int, start: int = 0) -> None:
        for index in range(start, start + count):
            # A sink that waits on the network would show up here.
            await asyncio.wait_for(self.sink(utterance(index)), 0.1)

    async def stop(self, bound: float = BOUND) -> float:
        began = time.monotonic()
        await asyncio.wait_for(self.runner.stop(timeout=0.5), bound)
        return time.monotonic() - began


async def eventually(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was never met")


def assert_no_leak(caplog: pytest.LogCaptureFixture) -> None:
    assert SECRET not in caplog.text


# --- refused, closed, policy ---------------------------------------------------


async def test_a_backend_that_is_not_listening_costs_no_caption(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    channel = TranscriptChannel(
        transcript_url(f"http://127.0.0.1:{port}", "ses_123"),
        reconnect_backoff_seconds=0.0,
        connect_timeout_seconds=0.5,
        ack_timeout_seconds=0.2,
    )
    pipeline = Pipeline(channel)
    await pipeline.speak(5)
    await eventually(lambda: pipeline.runner.send_failures == 5)

    assert pipeline.captions == [f"utt_{i}" for i in range(5)]
    # Retryable: kept in the channel buffer, not counted as dropped yet.
    assert channel.unacknowledged == 5
    assert await pipeline.stop() < 1.5
    assert_no_leak(caplog)


async def test_a_1011_close_is_reconnected_and_nothing_is_lost(caplog) -> None:
    caplog.set_level(logging.DEBUG)

    async def crash_once(connection: int, frame: dict, ws) -> bool | None:
        if connection == 1 and frame["id"] == "utt_2":
            await ws.close(code=1011)
            return True
        await ack(connection, frame, ws)
        return None

    async with Backend(crash_once) as backend:
        pipeline = Pipeline(channel_for(backend))
        await pipeline.speak(5)
        await eventually(lambda: len({f for _, f in backend.frames}) == 5)
        await eventually(lambda: pipeline.runner.channel.unacknowledged == 0)
        await pipeline.stop()

        delivered = {fid for _, fid in backend.frames}
        assert delivered == {f"utt_{i}" for i in range(5)}
        assert backend.connections == 2
        assert pipeline.captions == [f"utt_{i}" for i in range(5)]
        assert pipeline.runner.dropped == 0
    assert_no_leak(caplog)


@pytest.mark.parametrize("code", [1008, 4401])
async def test_a_policy_close_drops_later_transcripts_loudly_not_captions(
    code: int, caplog
) -> None:
    caplog.set_level(logging.DEBUG)

    async def policy(connection: int, frame: dict, ws) -> bool:
        await ws.close(code=code)
        return True

    async with Backend(policy) as backend:
        pipeline = Pipeline(channel_for(backend))
        await pipeline.speak(1)
        await eventually(lambda: backend.frames)
        await asyncio.sleep(0.05)
        await pipeline.speak(3, start=1)
        await eventually(lambda: pipeline.runner.dropped >= 3)

        assert pipeline.captions == [f"utt_{i}" for i in range(4)]
        assert backend.connections == 1  # no reconnect storm
        assert "closed by Backend policy" in caplog.text
        assert "BACKEND_CLIENT_ERROR" in caplog.text
        assert await pipeline.stop() < 1.5
    assert_no_leak(caplog)


# --- ACKs that do not match ----------------------------------------------------


async def test_out_of_order_unknown_and_malformed_answers_are_survived(
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    held: list[dict] = []

    async def chaos(connection: int, frame: dict, ws) -> None:
        await ws.send_bytes(b"\x00\x01binary")
        await ws.send_str("not json {")
        await ws.send_str("[1, 2, 3]")
        await ws.send_str(json.dumps({"type": FRAME_ACK}))
        await ws.send_str(json.dumps({"type": FRAME_ACK, "utteranceId": 42}))
        await ws.send_str(json.dumps({"type": FRAME_ACK, "utteranceId": "utt_9999"}))
        await ws.send_str(json.dumps({"type": "transcript.weird", "x": SECRET}))
        held.append(frame)
        if len(held) == 3:
            for earlier in reversed(held):  # ACK 2, 1, 0
                await ack(connection, earlier, ws)

    async with Backend(chaos) as backend:
        pipeline = Pipeline(channel_for(backend))
        await pipeline.speak(3)
        await eventually(lambda: len(backend.frames) == 3)
        await eventually(lambda: pipeline.runner.channel.unacknowledged == 0)

        assert backend.connections == 1
        assert [fid for _, fid in backend.frames] == ["utt_0", "utt_1", "utt_2"]
        assert pipeline.runner.send_failures == 0
        await pipeline.stop()
    assert_no_leak(caplog)


async def test_a_backend_that_never_acks_is_bounded_at_shutdown(caplog) -> None:
    caplog.set_level(logging.DEBUG)

    async def silent(connection: int, frame: dict, ws) -> None:
        return None

    async with Backend(silent) as backend:
        channel = channel_for(backend, ack_timeout_seconds=0.3)
        pipeline = Pipeline(channel)
        await pipeline.speak(3)
        await eventually(lambda: len(backend.frames) >= 3)
        took = await pipeline.stop()

        # Production: stop's 5 s join, or ack_timeout (5 s) + ws_close (1 s).
        assert took < 0.3 + 1.0 + 0.5
        assert pipeline.captions == ["utt_0", "utt_1", "utt_2"]
        assert "unacknowledged" in caplog.text
    assert_no_leak(caplog)


async def test_a_slow_backend_is_caught_up_once_speech_pauses(caplog) -> None:
    """ACKs later than the ACK timeout: churn while talking, convergence after."""

    caplog.set_level(logging.DEBUG)

    async def slow(connection: int, frame: dict, ws) -> None:
        await asyncio.sleep(0.15)
        await ack(connection, frame, ws)

    async with Backend(slow) as backend:
        channel = channel_for(backend, ack_timeout_seconds=0.1)
        pipeline = Pipeline(channel)
        for index in range(6):
            await pipeline.speak(1, start=index)
            await asyncio.sleep(0.12)
        await eventually(lambda: channel.unacknowledged == 0, timeout=5.0)

        delivered = {fid for _, fid in backend.frames}
        assert delivered == {f"utt_{i}" for i in range(6)}
        assert pipeline.runner.dropped == 0
        await pipeline.stop()
    assert_no_leak(caplog)


# --- an upgrade that is never answered -----------------------------------------


async def test_an_unanswered_upgrade_gives_up_and_the_next_connection_delivers() -> (
    None
):
    async with Backend(stall_first=True) as backend:
        channel = channel_for(backend, connect_timeout_seconds=0.3)
        pipeline = Pipeline(channel)
        try:
            await pipeline.speak(3)
            await asyncio.wait_for(eventually_stored(backend, 3), 2.0)
            assert pipeline.captions == ["utt_0", "utt_1", "utt_2"]
        finally:
            await pipeline.stop()


async def eventually_stored(backend: Backend, count: int) -> None:
    while len({fid for _, fid in backend.frames}) < count:
        await asyncio.sleep(0.01)


async def test_an_unanswered_upgrade_still_shuts_down_in_bound(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    async with Backend(stall_first=True) as backend:
        channel = channel_for(backend, connect_timeout_seconds=0.3)
        pipeline = Pipeline(channel, 4)
        await pipeline.speak(1)
        await eventually(lambda: backend.handshakes == 1)
        await pipeline.speak(9, start=1)

        assert pipeline.captions == [f"utt_{i}" for i in range(10)]
        # One is stuck in the handshake, four queued, the rest dropped loudly.
        assert pipeline.runner.dropped == 5
        assert await pipeline.stop() < 1.5
        # None is lost silently: each is stored, counted as dropped, or left
        # unacknowledged.
        stored = {fid for _, fid in backend.frames}
        accounted = pipeline.runner.dropped + len(stored) + channel.unacknowledged
        assert accounted >= 10
    assert_no_leak(caplog)
