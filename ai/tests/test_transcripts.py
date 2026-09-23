"""The transcript WebSocket: what it writes, what it keeps, and when it reopens.

Everything here runs against a local ``aiohttp`` server on the loopback
interface. No real Backend, no real interview audio, and no route outside
127.0.0.1 - the BE side of this contract does not exist yet, so an end-to-end
check is not available to write.
"""

import asyncio
import contextlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from irya_ai.backend import BackendError
from irya_ai.config import Settings
from irya_ai.schemas.wire import TranscriptPayload
from irya_ai.stt.http_logging import clear_protected_hosts, protected_hosts
from irya_ai.transcripts import (
    FRAME_ACK,
    FRAME_NACK,
    FRAME_UPSERT,
    TranscriptChannel,
    _Pending,
    build_transcript_channel,
    transcript_url,
)

TOKEN = "unit-test-token"


@pytest.fixture(autouse=True)
def _forget_protected_hosts():
    """Every channel here registers the loopback server's host; none may leak."""

    clear_protected_hosts()
    yield
    clear_protected_hosts()


def payload(
    utterance_id: str = "utt_001", text: str = "첫 발화입니다."
) -> TranscriptPayload:
    return TranscriptPayload(
        utterance_id=utterance_id,
        participant_id="candidate_123",
        speaker="CANDIDATE",
        text=text,
        started_at_ms=15_200,
        ended_at_ms=23_800,
    )


@dataclass
class Received:
    """One frame, and which connection carried it."""

    connection: int
    frame: dict


class FakeBackend:
    """A Backend that speaks the transcript contract, bound on 127.0.0.1.

    ``ack`` turns acknowledgement off, ``drop_first_after`` hangs up the first
    connection mid-session, ``drop_after`` hangs up every one of them,
    ``refuse_with`` answers the upgrade with a status instead of accepting it,
    and ``stall`` leaves the upgrade unanswered until the test releases it -
    the ways the real one can behave that this client has to survive. ``ack``
    and ``refuse_with`` are read per request, so a test can let a Backend
    recover mid-run.
    """

    def __init__(
        self,
        *,
        ack: bool = True,
        drop_first_after: int | None = None,
        drop_after: int | None = None,
        close_code: int = 1000,
        refuse_with: int | None = None,
        stall: asyncio.Event | None = None,
        nack: dict[str, str | None] | None = None,
        reply: Callable[[dict], dict | None] | None = None,
    ) -> None:
        self.ack = ack
        # Overrides every reply: whatever this returns is sent for a frame,
        # ``None`` meaning silence. For answers the contract does not produce.
        self.reply = reply
        # Utterance ids Backend refuses, mapped to the reason it gives (``None``
        # sends a NACK with no reason at all, which the contract does not
        # promise but a client should survive).
        self.nack = nack or {}
        self.drop_first_after = drop_first_after
        self.drop_after = drop_after
        self.close_code = close_code
        self.refuse_with = refuse_with
        self.stall = stall
        self.received: list[Received] = []
        self.handshakes: list[str | None] = []
        self.connected_at: list[float] = []
        self.connections = 0
        self._server: TestServer | None = None

    async def __aenter__(self) -> "FakeBackend":
        app = web.Application()
        app.router.add_get(
            "/internal/v1/sessions/{session_id}/transcripts", self._handle
        )
        self._server = TestServer(app)
        await self._server.start_server()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        assert self._server is not None
        await self._server.close()

    @property
    def base_url(self) -> str:
        """What ``BACKEND_BASE_URL`` would hold for this server."""

        assert self._server is not None
        return str(self._server.make_url("")).rstrip("/")

    def url(self, session_id: str = "ses_123") -> str:
        return transcript_url(self.base_url, session_id)

    def frames(self) -> list[dict]:
        return [item.frame for item in self.received]

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        self.handshakes.append(request.headers.get("Authorization"))
        if self.stall is not None:
            await self.stall.wait()
        if self.refuse_with is not None:
            return web.Response(status=self.refuse_with)

        self.connections += 1
        self.connected_at.append(time.monotonic())
        connection = self.connections
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        carried = 0
        async for message in ws:
            if message.type is not aiohttp.WSMsgType.TEXT:
                continue
            frame = json.loads(message.data)
            self.received.append(Received(connection, frame))
            carried += 1
            utterance_id = frame["utteranceId"]
            if self.reply is not None:
                answer = self.reply(frame)
                if answer is not None:
                    await ws.send_str(json.dumps(answer))
            elif utterance_id in self.nack:
                reply: dict = {"type": FRAME_NACK, "utteranceId": utterance_id}
                if self.nack[utterance_id] is not None:
                    reply["reason"] = self.nack[utterance_id]
                await ws.send_str(json.dumps(reply))
            elif self.ack:
                await ws.send_str(
                    json.dumps({"type": FRAME_ACK, "utteranceId": utterance_id})
                )
            if (
                self.drop_first_after is not None
                and connection == 1
                and carried >= self.drop_first_after
            ):
                await ws.close(code=self.close_code)
                break
            if self.drop_after is not None and carried >= self.drop_after:
                await ws.close(code=self.close_code)
                break
        return ws


def channel_for(backend: FakeBackend, session_id: str = "ses_123", **kwargs):
    kwargs.setdefault("reconnect_backoff_seconds", 0.0)
    return TranscriptChannel(
        backend.url(session_id),
        headers={"Authorization": f"Bearer {TOKEN}"},
        **kwargs,
    )


@contextlib.asynccontextmanager
async def closing_quickly(channel: TranscriptChannel):
    """Shut a channel down without sitting through a drain nobody will answer.

    ``aclose`` gives Backend the ACK timeout to catch up, which is right in
    production and five wasted seconds in a test whose Backend is silent on
    purpose. The body still runs at the real timeout, so nothing about the
    behaviour under test is shortened - only the teardown.
    """

    try:
        yield channel
    finally:
        channel.ack_timeout_seconds = 0.01
        await channel.aclose()


async def eventually(predicate, timeout: float = 2.0) -> None:
    """Wait for something the ACK reader does on its own task."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was never met")


async def test_a_confirmed_utterance_is_written_as_the_agreed_frame() -> None:
    async with FakeBackend() as backend:
        async with channel_for(backend) as channel:
            await channel.send(payload())
            await eventually(lambda: backend.frames())

        assert backend.frames() == [
            {
                "type": FRAME_UPSERT,
                "utteranceId": "utt_001",
                "participantId": "candidate_123",
                "speaker": "CANDIDATE",
                "text": "첫 발화입니다.",
                "startedAtMs": 15_200,
                "endedAtMs": 23_800,
            }
        ]


async def test_the_internal_credential_travels_in_the_handshake() -> None:
    """The contract puts it on the upgrade, not on every frame."""

    async with FakeBackend() as backend:
        async with channel_for(backend) as channel:
            await channel.send(payload())

        assert backend.handshakes == [f"Bearer {TOKEN}"]


async def test_the_session_is_in_the_path_and_not_in_the_frame() -> None:
    async with FakeBackend() as backend:
        async with channel_for(backend, "ses_abc") as channel:
            await channel.send(payload())
            await eventually(lambda: backend.frames())

        assert "sessionId" not in backend.frames()[0]
        assert channel.url.endswith("/sessions/ses_abc/transcripts")


async def test_an_ack_is_what_clears_an_utterance() -> None:
    """``send`` returns before the ACK, so the count is what proves it landed."""

    async with FakeBackend() as backend:
        async with channel_for(backend) as channel:
            await channel.send(payload())
            await eventually(lambda: channel.unacknowledged == 0)


async def test_an_unacknowledged_utterance_is_kept() -> None:
    async with FakeBackend(ack=False) as backend:
        async with closing_quickly(channel_for(backend)) as channel:
            await channel.send(payload())
            await eventually(lambda: backend.frames())

            assert channel.unacknowledged == 1


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "BACKEND_AUTH_FAILED", False),
        (403, "BACKEND_AUTH_FAILED", False),
        (404, "BACKEND_CLIENT_ERROR", False),
        (500, "BACKEND_REQUEST_FAILED", True),
    ],
)
async def test_a_refused_upgrade_is_classified_like_a_refused_post(
    status: int, code: str, retryable: bool
) -> None:
    """One status means one code on both transports."""

    async with FakeBackend(refuse_with=status) as backend:
        async with channel_for(backend) as channel:
            with pytest.raises(BackendError) as caught:
                await channel.send(payload())

            assert caught.value.code == code
            assert caught.value.retryable is retryable


async def test_a_non_retryable_handshake_failure_closes_the_channel() -> None:
    """A bad credential does not improve by filling the buffer and retrying."""

    async with FakeBackend(refuse_with=401) as backend:
        channel = channel_for(backend)
        try:
            with pytest.raises(BackendError, match="BACKEND_AUTH_FAILED"):
                await channel.send(payload("utt_001"))

            backend.refuse_with = None
            with pytest.raises(BackendError, match="BACKEND_AUTH_FAILED"):
                await channel.send(payload("utt_002"))

            assert len(backend.handshakes) == 1
            assert channel.unacknowledged == 1
        finally:
            await channel.aclose()


async def test_a_policy_close_does_not_start_a_reconnect_loop() -> None:
    async with FakeBackend(ack=False, drop_after=1, close_code=1008) as backend:
        channel = channel_for(backend)
        try:
            await channel.send(payload("utt_001"))
            await eventually(lambda: channel._closed)

            with pytest.raises(BackendError, match="BACKEND_CLIENT_ERROR"):
                await channel.send(payload("utt_002"))

            assert backend.connections == 1
        finally:
            await channel.aclose()


async def test_a_backend_that_is_not_listening_is_retryable() -> None:
    channel = TranscriptChannel(
        transcript_url("http://127.0.0.1:1", "ses_123"),
        reconnect_backoff_seconds=0.0,
        connect_timeout_seconds=2.0,
    )
    try:
        with pytest.raises(BackendError) as caught:
            await channel.send(payload())

        assert caught.value.code == "BACKEND_REQUEST_FAILED"
        assert caught.value.retryable is True
    finally:
        await channel.aclose()


async def test_a_refused_utterance_is_still_kept_for_the_next_connection() -> None:
    """A raise is not a lost utterance while there is room in the buffer."""

    async with FakeBackend(refuse_with=500) as backend:
        async with channel_for(backend) as channel:
            with pytest.raises(BackendError):
                await channel.send(payload())

            assert channel.unacknowledged == 1


def carried(backend: FakeBackend) -> list[tuple[int, str]]:
    """Which connection carried which utterance, in the order Backend saw them."""

    return [(item.connection, item.frame["utteranceId"]) for item in backend.received]


async def test_a_backend_that_hangs_up_is_reconnected_without_another_utterance() -> (
    None
):
    """The ACK reader ending is the notice, and it must not wait for a send.

    Backend takes the frame and closes. Nothing else is written, so if the
    reconnect were the next ``send``'s job - and the interview's next
    confirmed utterance may be a minute away - the frame would sit
    unacknowledged on a socket nobody is reading until then.
    """

    async with FakeBackend(ack=False, drop_first_after=1) as backend:
        async with closing_quickly(channel_for(backend)) as channel:
            await channel.send(payload("utt_001"))

            await eventually(
                lambda: carried(backend) == [(1, "utt_001"), (2, "utt_001")]
            )
            assert channel.unacknowledged == 1


async def test_a_backend_that_keeps_hanging_up_keeps_being_reconnected() -> None:
    """The second hang-up is the one that used to be lost.

    A recovery opens a connection of its own, and that connection's reader can
    end while the recovery that opened it is still running. The notice has
    nowhere to go then except onto the recovery already in flight, and a
    recovery that only ever made one attempt dropped it - leaving the buffer
    waiting for a ``send`` that an interview between utterances will not make.
    """

    async with FakeBackend(ack=False, drop_after=1) as backend:
        async with closing_quickly(channel_for(backend)) as channel:
            await channel.send(payload("utt_001"))

            await eventually(lambda: backend.connections >= 4, timeout=5.0)
            assert carried(backend)[:4] == [
                (1, "utt_001"),
                (2, "utt_001"),
                (3, "utt_001"),
                (4, "utt_001"),
            ]
            assert channel.unacknowledged == 1


async def test_reconnect_backoff_is_applied_between_connections() -> None:
    async with FakeBackend(ack=False, drop_first_after=1) as backend:
        async with closing_quickly(
            channel_for(backend, reconnect_backoff_seconds=0.05)
        ) as channel:
            await channel.send(payload("utt_001"))
            await eventually(lambda: backend.connections == 2)

        assert backend.connected_at[1] - backend.connected_at[0] >= 0.04


async def test_a_connection_that_dies_during_a_recovery_is_still_answered() -> None:
    """Single-flight, but not at the price of forgetting the second notice.

    The end-to-end version of this depends on which of two tasks the loop runs
    first. Driving ``_start_recovery`` directly is what pins the ordering: the
    second call lands while the first recovery is provably mid-attempt.
    """

    channel = TranscriptChannel("wss://backend.invalid/x")
    channel._pending["utt_001"] = _Pending({"type": FRAME_UPSERT})

    rounds = 0
    holding = asyncio.Event()

    async def attempt() -> None:
        nonlocal rounds
        rounds += 1
        if rounds == 1:
            await holding.wait()

    channel._deliver_buffered = attempt

    channel._start_recovery()
    await eventually(lambda: rounds == 1)

    # The socket this very recovery opened has just died.
    channel._start_recovery()
    holding.set()

    recovery = channel._recovery
    assert recovery is not None
    await recovery

    assert rounds == 2


async def test_a_dropped_connection_resends_what_was_never_acknowledged() -> None:
    async with FakeBackend(ack=False, drop_first_after=1) as backend:
        async with closing_quickly(channel_for(backend)) as channel:
            await channel.send(payload("utt_001"))

            # Waiting for the resend rather than for the first frame: what
            # comes next has to be written onto the second connection, and
            # which connection is current when a send lands is otherwise a
            # race between this task and the socket's own end - which is what
            # made this test pass on Linux and fail on Windows.
            await eventually(
                lambda: carried(backend) == [(1, "utt_001"), (2, "utt_001")]
            )

            await channel.send(payload("utt_002"))
            await eventually(lambda: len(backend.received) == 3)

        # The second connection carried the unacknowledged first utterance
        # again, which Backend upserts onto the same row rather than doubling.
        assert carried(backend) == [
            (1, "utt_001"),
            (2, "utt_001"),
            (2, "utt_002"),
        ]


async def test_a_silent_backend_is_treated_as_a_dead_connection() -> None:
    """An open socket that never ACKs is indistinguishable from a half-open one."""

    async with FakeBackend(ack=False) as backend:
        async with channel_for(backend, ack_timeout_seconds=0.05) as channel:
            await channel.send(payload("utt_001"))
            await eventually(lambda: len(backend.received) == 1)

            await asyncio.sleep(0.1)
            await channel.send(payload("utt_002"))
            await eventually(lambda: len(backend.received) == 3)

        assert backend.connections == 2


async def test_a_full_buffer_refuses_the_utterance_rather_than_pretending() -> None:
    """The one case where an utterance really is dropped, and it says so."""

    async with FakeBackend(ack=False) as backend:
        async with closing_quickly(channel_for(backend, max_pending=1)) as channel:
            await channel.send(payload("utt_001"))
            await eventually(lambda: len(backend.received) == 1)

            with pytest.raises(BackendError) as caught:
                await channel.send(payload("utt_002"))

            assert caught.value.code == "BACKEND_TRANSCRIPT_BUFFER_FULL"
            assert caught.value.retryable is False
            assert channel.unacknowledged == 1
            assert len(backend.received) == 1


async def test_a_refused_utterance_leaves_the_buffer_and_is_never_resent() -> None:
    """Backend's NACK means "do not send this again"; the client must obey.

    Left in the buffer, the frame would be written on every reconnect and
    refused every time, with the ACK timeout forcing those reconnects.
    """

    async with FakeBackend(nack={"utt_bad": "SCHEMA"}, drop_after=3) as backend:
        async with closing_quickly(channel_for(backend)) as channel:
            await channel.send(payload("utt_001"))
            await channel.send(payload("utt_bad"))
            await channel.send(payload("utt_002"))
            await eventually(lambda: channel.unacknowledged == 0)

            assert channel.refused == {"utt_bad": "SCHEMA"}
            # Backend hung up after three frames; the recovery that follows
            # must have nothing left to carry, so no fourth frame ever lands.
            await eventually(lambda: backend.connections >= 1)
            await asyncio.sleep(0.3)
            assert [u for _, u in carried(backend)] == ["utt_001", "utt_bad", "utt_002"]
            assert channel.unacknowledged == 0


async def test_a_nack_without_a_reason_is_still_a_refusal() -> None:
    async with FakeBackend(nack={"utt_bad": None}) as backend:
        async with closing_quickly(channel_for(backend)) as channel:
            await channel.send(payload("utt_bad"))
            await eventually(lambda: channel.unacknowledged == 0)

            assert channel.refused == {"utt_bad": "?"}


async def test_a_nack_for_an_unknown_utterance_changes_nothing() -> None:
    # Backend answers about something it never got from this client.
    misaddressed = FakeBackend(
        reply=lambda _frame: {"type": FRAME_NACK, "utteranceId": "utt_zzz"}
    )
    async with misaddressed as backend:
        async with closing_quickly(channel_for(backend)) as channel:
            await channel.send(payload("utt_001"))
            await eventually(lambda: len(backend.received) == 1)
            await asyncio.sleep(0.05)

            assert channel.unacknowledged == 1
            assert channel.refused == {}


async def test_a_corrected_utterance_replaces_the_one_in_flight() -> None:
    """Backend upserts on ``(sessionId, utteranceId)``, so the two are one row."""

    async with FakeBackend(ack=False) as backend:
        async with closing_quickly(channel_for(backend, max_pending=1)) as channel:
            await channel.send(payload("utt_001", "첫 발화입니다."))
            await channel.send(payload("utt_001", "첫 발화입니다. 정정합니다."))
            await eventually(lambda: len(backend.received) == 2)

            assert channel.unacknowledged == 1
            assert backend.frames()[1]["text"] == "첫 발화입니다. 정정합니다."
            assert backend.connections == 2


async def test_an_old_ack_cannot_clear_an_unwritten_correction() -> None:
    """ACK has no revision, so an unsent replacement is never its target."""

    channel = TranscriptChannel("wss://backend.invalid/x")
    channel._pending["utt_001"] = _Pending(
        {"type": FRAME_UPSERT, "text": "원본"},
        exposed=True,
        written_at=time.monotonic(),
    )
    async with channel._lock:
        admitted, isolate_revision = channel._admit(
            "utt_001", {"type": FRAME_UPSERT, "text": "교정본"}
        )

    async def one_ack():
        yield type(
            "Ack",
            (),
            {
                "type": aiohttp.WSMsgType.TEXT,
                "data": json.dumps({"type": FRAME_ACK, "utteranceId": "utt_001"}),
            },
        )()

    await channel._read_acks(one_ack())  # type: ignore[arg-type]

    assert admitted and isolate_revision
    assert channel.unacknowledged == 1
    assert channel._pending["utt_001"].frame["text"] == "교정본"


async def test_sends_arriving_together_cannot_take_the_buffer_over_the_cap() -> None:
    """The cap is a memory bound, so it has to hold when sends overlap."""

    async with FakeBackend(ack=False) as backend:
        async with closing_quickly(channel_for(backend, max_pending=2)) as channel:
            results = await asyncio.gather(
                *(channel.send(payload(f"utt_{index:03d}")) for index in range(6)),
                return_exceptions=True,
            )

            assert channel.unacknowledged == 2
            refused = [item for item in results if isinstance(item, BackendError)]
            assert len(refused) == 4
            assert {item.code for item in refused} == {"BACKEND_TRANSCRIPT_BUFFER_FULL"}


async def test_the_slot_a_send_checked_for_is_the_slot_it_takes() -> None:
    """Checking the cap and taking the slot have to be one critical section.

    Every refused send goes looking for room before it gives up, so they all
    come back to the cap at once. Here all three are parked inside that search
    before a single slot is freed, so they come back to a buffer with room for
    exactly one of them: if the check and the insert are two critical sections,
    each of the three sees that slot and each of them takes it.
    """

    channel = TranscriptChannel("wss://backend.invalid/x", max_pending=2)

    async def nothing() -> None:
        return None

    channel._ensure_connection = nothing
    channel._flush = nothing

    await channel.send(payload("utt_000"))
    await channel.send(payload("utt_001"))
    assert channel.unacknowledged == 2

    released = asyncio.Event()
    arrived: list[bool] = []

    async def attempt() -> None:
        # Deliberately frees nothing: the slot arrives once every refused send
        # is in here, so none of them can be let past ahead of the others.
        arrived.append(True)
        await released.wait()

    channel._deliver_buffered = attempt

    senders = [
        asyncio.create_task(channel.send(payload(f"utt_{index:03d}")))
        for index in (2, 3, 4)
    ]
    await eventually(lambda: len(arrived) == 3)

    # The ACK that frees exactly one slot, with all three waiting on it.
    channel._pending.pop("utt_000")
    released.set()
    results = await asyncio.gather(*senders, return_exceptions=True)

    assert channel.unacknowledged == 2
    refused = [item for item in results if isinstance(item, BackendError)]
    assert len(refused) == 2
    assert {item.code for item in refused} == {"BACKEND_TRANSCRIPT_BUFFER_FULL"}


async def test_a_full_buffer_still_lets_the_buffered_frames_reach_backend() -> None:
    """The cap refuses a new utterance; it must not refuse the reconnect too.

    Backend being down is what fills the buffer, so checking the cap before
    the connection is what makes recovery impossible: every later utterance
    is refused before a reconnect is attempted, and the frames already held
    are never written. Their ACKs are the only thing that makes room.
    """

    async with FakeBackend(refuse_with=503) as backend:
        async with closing_quickly(channel_for(backend, max_pending=1)) as channel:
            with pytest.raises(BackendError, match="BACKEND_REQUEST_FAILED"):
                await channel.send(payload("utt_001"))
            assert channel.unacknowledged == 1

            backend.refuse_with = None

            # Still refused - utt_001 is holding the one slot, and its ACK
            # cannot have arrived yet - but the buffered frame now goes out.
            with pytest.raises(BackendError, match="BACKEND_TRANSCRIPT_BUFFER_FULL"):
                await channel.send(payload("utt_002"))

            await eventually(lambda: channel.unacknowledged == 0)
            await channel.send(payload("utt_002"))
            await eventually(
                lambda: (
                    [frame["utteranceId"] for frame in backend.frames()]
                    == ["utt_001", "utt_002"]
                )
            )


async def test_a_cancelled_send_propagates_and_keeps_the_utterance() -> None:
    """Whatever cancels the media path is not this channel's to swallow."""

    stall = asyncio.Event()
    async with FakeBackend(stall=stall) as backend:
        channel = channel_for(backend)
        try:
            sending = asyncio.create_task(channel.send(payload()))
            await eventually(lambda: bool(backend.handshakes))

            sending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sending

            assert channel.unacknowledged == 1
        finally:
            stall.set()
            channel.ack_timeout_seconds = 0.01
            await channel.aclose()


async def test_a_caller_cancelled_while_the_reader_is_dropped_stays_cancelled() -> None:
    """Dropping a connection cancels the ACK reader, and waits for it to end.

    A cancel aimed at the ``send`` or ``aclose`` doing the dropping arrives at
    that same ``await``, and the two are not the same thing: the reader's is
    expected and swallowed, the caller's has to keep travelling. Reaching for
    the drop directly is the only way to hold the two apart deterministically
    - a real reader ends the instant it is cancelled.
    """

    released = asyncio.Event()

    async def stubborn_reader() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # Still on its way out when the caller's own cancel lands.
            await released.wait()
            raise

    channel = TranscriptChannel("wss://backend.invalid/x")
    reader = asyncio.create_task(stubborn_reader())
    channel._reader = reader

    dropping = asyncio.create_task(channel._drop_connection())
    await eventually(lambda: channel._reader is None)

    dropping.cancel()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await dropping

    with contextlib.suppress(asyncio.CancelledError):
        await reader


class FakeSocket:
    """A socket that records the one thing these tests watch: being closed.

    The real one cannot stand in here. Both tests below need the close to be
    observable *after* the cancel that interrupted it, and a real socket's is
    over the moment its session is - which is the very leak being checked for.
    """

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class StalledSocket(FakeSocket):
    """A socket whose writes never come back, the way a paused writer's do not."""

    def __init__(self) -> None:
        super().__init__()
        self.writing = asyncio.Event()

    async def send_str(self, _data: str) -> None:
        self.writing.set()
        await asyncio.Event().wait()


async def test_a_cancelled_drop_still_closes_the_socket_it_detached() -> None:
    """The cancel travels on, and the socket does not stay open behind it.

    Not swallowing the caller's cancel is only half the job. ``_detach`` takes
    the socket out of ``_ws`` before the wait that the cancel lands on, so by
    then nothing else holds it: whoever is interrupted here is the last one
    that could ever close it, and an interview's worth of half-open sockets is
    what leaving them to the session close would mean.
    """

    released = asyncio.Event()

    async def stubborn_reader() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await released.wait()
            raise

    channel = TranscriptChannel("wss://backend.invalid/x")
    socket = FakeSocket()
    channel._ws = socket
    reader = asyncio.create_task(stubborn_reader())
    channel._reader = reader

    dropping = asyncio.create_task(channel._drop_connection())
    await eventually(lambda: channel._ws is None)

    dropping.cancel()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await dropping

    await eventually(lambda: socket.closed)

    with contextlib.suppress(asyncio.CancelledError):
        await reader


async def test_a_stalled_write_does_not_hold_up_closing() -> None:
    """``send_str`` is a wait, not a step, and the state lock may not span it.

    aiohttp pauses its writer once the transport's buffer is over the high
    water mark and does not come back until the peer reads - which a Backend
    that has stopped reading never does. A write holding the state lock across
    that is a ``aclose`` that never returns, not one that returns late, and the
    frames it was holding go nowhere either.
    """

    channel = TranscriptChannel("wss://backend.invalid/x", ack_timeout_seconds=30.0)
    socket = StalledSocket()
    channel._ws = socket
    # ``_usable`` wants a live reader too, and this one never ends on its own.
    channel._reader = asyncio.create_task(asyncio.Event().wait())

    sending = asyncio.create_task(channel.send(payload()))
    try:
        await socket.writing.wait()

        channel.ack_timeout_seconds = 0.01
        await asyncio.wait_for(channel.aclose(), 2.0)

        assert socket.closed
        # Refused, not lost: the frame is still there to be written again.
        assert channel.unacknowledged == 1
    finally:
        sending.cancel()
        with contextlib.suppress(BackendError, asyncio.CancelledError):
            await sending


async def test_a_stalled_handshake_does_not_hold_up_closing() -> None:
    """The state is shared; the waiting is not allowed to be.

    A connect can sit there for the whole connect timeout, and an abandoned
    socket's close handshake for as long again. Holding the state lock across
    either of them makes every concurrent send and the shutdown queue behind
    them, which on the media path is the interview waiting on Backend.
    """

    stall = asyncio.Event()
    async with FakeBackend(stall=stall) as backend:
        channel = channel_for(backend, connect_timeout_seconds=30.0)
        sending = asyncio.create_task(channel.send(payload()))
        try:
            await eventually(lambda: bool(backend.handshakes))

            # ``wait_for`` rather than a stopwatch: a stalled handshake has no
            # timeout of its own, so a close queued behind it does not come
            # back late - it does not come back.
            await asyncio.wait_for(channel.aclose(), 2.0)
        finally:
            stall.set()
            sending.cancel()
            with contextlib.suppress(BackendError, asyncio.CancelledError):
                await sending


async def test_closing_waits_for_the_outstanding_acks() -> None:
    async with FakeBackend() as backend:
        channel = channel_for(backend)
        await channel.send(payload())
        await channel.aclose()

        assert channel.unacknowledged == 0


async def test_closing_gives_up_after_the_ack_timeout() -> None:
    """A Backend that never answers must not hold the shutdown open."""

    async with FakeBackend(ack=False) as backend:
        channel = channel_for(backend, ack_timeout_seconds=0.05)
        await channel.send(payload())

        started = time.monotonic()
        await channel.aclose()

        assert channel.unacknowledged == 1
        assert time.monotonic() - started < 1.0


async def test_closing_twice_is_harmless() -> None:
    async with FakeBackend() as backend:
        channel = channel_for(backend)
        await channel.send(payload())
        await channel.aclose()
        await channel.aclose()


async def test_a_closed_channel_refuses_further_utterances() -> None:
    async with FakeBackend() as backend:
        channel = channel_for(backend)
        await channel.aclose()

        with pytest.raises(BackendError, match="BACKEND_TRANSCRIPT_CHANNEL_CLOSED"):
            await channel.send(payload())


async def test_closing_does_not_admit_a_send_that_was_waiting_for_state() -> None:
    """Shutdown wins even when a send passed its fast check just beforehand."""

    channel = TranscriptChannel("wss://backend.invalid/x")
    await channel._lock.acquire()
    sending = asyncio.create_task(channel.send(payload()))
    await asyncio.sleep(0)

    closing = asyncio.create_task(channel.aclose())
    await eventually(lambda: channel._closed)
    channel._lock.release()

    with pytest.raises(BackendError, match="BACKEND_TRANSCRIPT_CHANNEL_CLOSED"):
        await sending
    await closing

    assert channel.unacknowledged == 0


async def test_the_backend_host_is_registered_for_log_redaction() -> None:
    """Nothing else on the transcript path would register it."""

    async with FakeBackend() as backend:
        host = backend.base_url.split("//", 1)[1].split(":")[0]
        async with channel_for(backend):
            assert host in protected_hosts()


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        # The contract's docker compose address, which is what a local run has.
        ("http://backend:8000", "ws://backend:8000"),
        ("https://backend.invalid", "wss://backend.invalid"),
        ("https://backend.invalid/", "wss://backend.invalid"),
        ("ws://backend:8000", "ws://backend:8000"),
        ("wss://backend.invalid", "wss://backend.invalid"),
    ],
)
def test_the_websocket_address_is_derived_from_the_http_base_url(
    base_url: str, expected: str
) -> None:
    assert transcript_url(base_url, "ses_123") == (
        f"{expected}/internal/v1/sessions/ses_123/transcripts"
    )


def test_an_unconfigured_backend_has_no_websocket_address() -> None:
    with pytest.raises(BackendError, match="BACKEND_BASE_URL_NOT_SET"):
        transcript_url("   ", "ses_123")


@pytest.mark.parametrize("base_url", ["backend:8000", "ftp://backend", "https://"])
def test_a_base_url_that_is_not_a_backend_address_is_refused(base_url: str) -> None:
    with pytest.raises(BackendError, match="BACKEND_BASE_URL_INVALID"):
        transcript_url(base_url, "ses_123")


@pytest.mark.parametrize("session_id", ["", "   ", "ses/../other", "..", "a/b"])
def test_a_session_id_that_would_rewrite_the_path_is_refused(session_id: str) -> None:
    """Refused before anything is opened, the same way the HTTP path refuses it."""

    with pytest.raises(BackendError, match="BACKEND_INVALID_SESSION_ID"):
        transcript_url("https://backend.invalid", session_id)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ack_timeout_seconds": 0},
        {"max_pending": 0},
        {"reconnect_backoff_seconds": -1.0},
        {"connect_timeout_seconds": 0},
    ],
)
def test_a_channel_refuses_settings_it_could_not_act_on(kwargs: dict) -> None:
    with pytest.raises(ValueError, match=next(iter(kwargs))):
        TranscriptChannel("wss://backend.invalid/x", **kwargs)


def test_build_transcript_channel_carries_settings_onto_the_channel() -> None:
    settings = Settings(
        _env_file=None,
        backend_base_url="https://backend.invalid/",
        backend_api_key=TOKEN,
        transcript_ack_timeout_seconds=3,
        transcript_max_pending=7,
        transcript_reconnect_backoff_seconds=0.25,
    )

    channel = build_transcript_channel(settings, "ses_123")

    assert channel.url == (
        "wss://backend.invalid/internal/v1/sessions/ses_123/transcripts"
    )
    assert channel.ack_timeout_seconds == 3
    assert channel.max_pending == 7
    assert channel.reconnect_backoff_seconds == 0.25


def test_build_transcript_channel_refuses_an_unconfigured_backend() -> None:
    with pytest.raises(BackendError, match="BACKEND_BASE_URL"):
        build_transcript_channel(Settings(_env_file=None), "ses_123")
