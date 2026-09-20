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
    FRAME_UPSERT,
    TranscriptChannel,
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
    connection mid-session, and ``refuse_with`` answers the upgrade with a
    status instead of accepting it - the three ways the real one can behave
    that this client has to survive.
    """

    def __init__(
        self,
        *,
        ack: bool = True,
        drop_first_after: int | None = None,
        refuse_with: int | None = None,
    ) -> None:
        self.ack = ack
        self.drop_first_after = drop_first_after
        self.refuse_with = refuse_with
        self.received: list[Received] = []
        self.handshakes: list[str | None] = []
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
        if self.refuse_with is not None:
            return web.Response(status=self.refuse_with)

        self.connections += 1
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
            if self.ack:
                await ws.send_str(
                    json.dumps({"type": FRAME_ACK, "utteranceId": frame["utteranceId"]})
                )
            if (
                self.drop_first_after is not None
                and connection == 1
                and carried >= self.drop_first_after
            ):
                await ws.close()
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


async def test_a_dropped_connection_resends_what_was_never_acknowledged() -> None:
    async with FakeBackend(ack=False, drop_first_after=1) as backend:
        async with closing_quickly(channel_for(backend)) as channel:
            await channel.send(payload("utt_001"))
            await eventually(lambda: len(backend.received) == 1)

            await channel.send(payload("utt_002"))
            await eventually(lambda: len(backend.received) == 3)

        # The second connection carried the unacknowledged first utterance
        # again, which Backend upserts onto the same row rather than doubling.
        assert [
            (item.connection, item.frame["utteranceId"]) for item in backend.received
        ] == [
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


async def test_a_corrected_utterance_replaces_the_one_in_flight() -> None:
    """Backend upserts on ``(sessionId, utteranceId)``, so the two are one row."""

    async with FakeBackend(ack=False) as backend:
        async with closing_quickly(channel_for(backend, max_pending=1)) as channel:
            await channel.send(payload("utt_001", "첫 발화입니다."))
            await channel.send(payload("utt_001", "첫 발화입니다. 정정합니다."))
            await eventually(lambda: len(backend.received) == 2)

            assert channel.unacknowledged == 1
            assert backend.frames()[1]["text"] == "첫 발화입니다. 정정합니다."


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
