"""The Agent's transcript channel to Backend: one WebSocket per session.

The agreed contract carries confirmed utterances over
``WS /internal/v1/sessions/{sessionId}/transcripts`` rather than the HTTP POST
this branch first implemented. The transport is settled; the frame shape, the
ACK and the internal authentication method below are the contract proposal's
values and are not independently confirmed - see ``OPEN_QUESTIONS.md``.

One connection per session. The Agent writes one JSON text frame per confirmed
utterance::

    {"type": "transcript.upsert", "utteranceId": "utt_001", ...}

and Backend answers each one::

    {"type": "transcript.ack", "utteranceId": "utt_001"}

Backend keys on ``(sessionId, utteranceId)`` and upserts, so a frame resent
after a reconnect is not a duplicate. That is what makes the buffer here safe:
:meth:`TranscriptChannel.send` returns as soon as the frame is written, keeps
it until its ACK arrives, and writes everything still unacknowledged again on
the next connection.

**This must not be allowed to stop the interview.** The contract is explicit
that a WebSocket failure may not interrupt the call, the recording or LiveKit's
live captions, and this module cannot enforce that from in here - it raises
:class:`~irya_ai.backend.BackendError` like the HTTP client does, and the
caller in the media path has to catch it. A raise is not a lost utterance
while there is room in the buffer; ``BACKEND_TRANSCRIPT_BUFFER_FULL`` is the
one that says transcripts are now being dropped.

The ACK timeout, the buffer cap and the reconnect backoff are provisional.
They are the contract's open item 3 - "ACK 대기 시간·버퍼 상한·재연결 정책" -
which is not agreed with Backend yet; the defaults in :mod:`irya_ai.config`
keep a local run honest rather than settle anything.

Suggestion, Context and Review stay on HTTP in :mod:`irya_ai.backend`. This
module borrows that module's :func:`~irya_ai.backend.status_error`,
:func:`~irya_ai.backend.path_segment` and
:func:`~irya_ai.backend.auth_headers` so one status, one bad id and one unset
key mean the same thing on both transports.
"""

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass

import aiohttp

from irya_ai.backend import BackendError, auth_headers, path_segment, status_error
from irya_ai.config import Settings
from irya_ai.schemas.wire import TranscriptPayload
from irya_ai.stt.http_logging import protect_host

logger = logging.getLogger(__name__)

# The two frame types on this socket. ``type`` identifies the frame, not the
# utterance, which is why it is not a field on :class:`TranscriptPayload`.
FRAME_UPSERT = "transcript.upsert"
FRAME_ACK = "transcript.ack"

# ``http`` and ``https`` are what ``BACKEND_BASE_URL`` realistically holds; the
# ``ws`` pair is accepted so a WebSocket-only override does not have to be
# written back as HTTP to be understood.
_WS_SCHEMES = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}


def transcript_url(base_url: str, session_id: str) -> str:
    """The session's transcript WebSocket address, derived from the HTTP base URL.

    The contract puts the WebSocket on the Backend host, so it is derived
    rather than configured separately: there is no second private URL to set,
    to get out of step, or to keep out of the logs. ``http`` becomes ``ws``,
    ``https`` becomes ``wss``, and the rest of the base URL is left alone.

    Raises :class:`~irya_ai.backend.BackendError` before anything is opened -
    ``BACKEND_BASE_URL_NOT_SET``, ``BACKEND_BASE_URL_INVALID``, or
    ``BACKEND_INVALID_SESSION_ID`` from :func:`~irya_ai.backend.path_segment`.
    """

    base = base_url.strip().rstrip("/")
    if not base:
        raise BackendError("BACKEND_BASE_URL_NOT_SET", retryable=False)

    scheme, separator, rest = base.partition("://")
    ws_scheme = _WS_SCHEMES.get(scheme.lower()) if separator else None
    if not ws_scheme or not rest:
        raise BackendError("BACKEND_BASE_URL_INVALID", retryable=False)

    session = path_segment(session_id)
    return f"{ws_scheme}://{rest}/internal/v1/sessions/{session}/transcripts"


@dataclass
class _Pending:
    """One frame waiting for its ACK.

    ``written_at`` is ``None`` until the frame has been written on the current
    connection, which is what makes a reconnect resend exactly the frames the
    new socket has not carried yet.
    """

    frame: dict[str, object]
    written_at: float | None = None


class TranscriptChannel:
    """One session's transcript WebSocket.

    Constructing one registers the Backend host for log redaction, the same
    way :class:`~irya_ai.backend.BackendClient` does for its ``base_url`` -
    nothing else on the transcript path would otherwise register it.

    Unlike that client, this one owns its ``aiohttp.ClientSession``: the
    connection is the thing being managed here, it is opened lazily on the
    first send and replaced on every reconnect, so ownership cannot be split
    with the caller. :meth:`aclose` closes both.

    Not safe to share across sessions - one instance is one ``sessionId`` -
    and its own state is guarded by a lock, so concurrent sends from the STT
    pipeline serialise rather than interleave frames.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        ack_timeout_seconds: float = 5.0,
        max_pending: int = 200,
        reconnect_backoff_seconds: float = 0.5,
        connect_timeout_seconds: float = 10.0,
    ) -> None:
        if ack_timeout_seconds <= 0:
            raise ValueError("ack_timeout_seconds must be positive")
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        if reconnect_backoff_seconds < 0:
            raise ValueError("reconnect_backoff_seconds must not be negative")
        if connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be positive")

        protect_host(url)

        self.url = url
        self.ack_timeout_seconds = ack_timeout_seconds
        self.max_pending = max_pending
        self.reconnect_backoff_seconds = reconnect_backoff_seconds
        self.connect_timeout_seconds = connect_timeout_seconds

        self._headers = dict(headers or {})
        self._pending: dict[str, _Pending] = {}
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task[None] | None = None
        self._reader_failure: BaseException | None = None
        self._closed = False
        self._lock = asyncio.Lock()
        # Set while nothing is waiting for an ACK, so :meth:`aclose` can wait
        # for the drain instead of polling for it.
        self._drained = asyncio.Event()
        self._drained.set()

    @property
    def unacknowledged(self) -> int:
        """How many utterances Backend has not acknowledged yet."""

        return len(self._pending)

    async def __aenter__(self) -> "TranscriptChannel":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def send(self, payload: TranscriptPayload) -> None:
        """Write one confirmed utterance, without waiting for its ACK.

        Returning does not mean Backend stored it: the frame is held until the
        ACK arrives and is written again on the next connection if the socket
        dies first. Raises :class:`~irya_ai.backend.BackendError` and nothing
        else, and the payload stays buffered when it does - unless the buffer
        is full, which is ``BACKEND_TRANSCRIPT_BUFFER_FULL`` and the only case
        where an utterance is refused outright.

        The caller is in the media path. It must catch this.
        """

        if self._closed:
            raise BackendError("BACKEND_TRANSCRIPT_CHANNEL_CLOSED", retryable=False)

        frame: dict[str, object] = {
            "type": FRAME_UPSERT,
            # ``by_alias`` is the whole point of the wire models - the agreed
            # contract is camelCase, and the field names are snake_case here.
            **payload.model_dump(by_alias=True, mode="json"),
        }
        utterance_id = payload.utterance_id

        async with self._lock:
            self._report_reader_failure()

            # A corrected FINAL for an utterance already in flight replaces it
            # rather than counting against the cap: Backend upserts on
            # ``(sessionId, utteranceId)``, so the two are one row there too.
            if (
                utterance_id not in self._pending
                and len(self._pending) >= self.max_pending
            ):
                logger.warning(
                    "Transcript buffer full (%d unacknowledged); dropping utterance",
                    len(self._pending),
                )
                raise BackendError("BACKEND_TRANSCRIPT_BUFFER_FULL", retryable=False)

            self._pending[utterance_id] = _Pending(frame)
            self._drained.clear()

            if self._ack_overdue():
                # The socket is open and Backend is not answering on it. That
                # is indistinguishable from a half-open connection from here,
                # so it is treated as one: drop it and let the reconnect below
                # write everything still pending onto the new socket.
                logger.warning("Transcript ACK overdue; reopening the channel")
                await self._drop_connection()

            await self._ensure_connection()
            try:
                await self._flush()
            except BackendError:
                # The socket was open a moment ago and the write did not land,
                # so it went stale between utterances - a Backend restart, an
                # idle timeout on something in between. One fresh connection,
                # which also rewrites everything still pending, and then the
                # caller hears about it. A refused *connect* is deliberately
                # not retried here: Backend being down is not something an
                # immediate second attempt changes, and this call is standing
                # in the media path while it waits.
                await self._drop_connection()
                await self._ensure_connection()
                await self._flush()

    async def aclose(self) -> None:
        """Close the channel, giving Backend the ACK timeout to answer.

        Idempotent. Anything still unacknowledged when the wait runs out is
        reported as a count and then abandoned - what the Agent should do with
        it is part of the contract's open item 3, not something to decide in a
        shutdown path.
        """

        if self._closed and self._session is None:
            return
        self._closed = True

        async with self._lock:
            self._report_reader_failure()
            if self._pending and self._ws is not None and not self._ws.closed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._drained.wait(), self.ack_timeout_seconds
                    )

            if self._pending:
                logger.warning(
                    "Transcript channel closing with %d utterance(s) unacknowledged",
                    len(self._pending),
                )

            await self._drop_connection()
            session, self._session = self._session, None
            if session is not None:
                await session.close()

    async def _ensure_connection(self) -> None:
        """Open the socket if there is not a usable one, and start its reader."""

        if self._ws is not None and not self._ws.closed:
            return

        reconnecting = self._session is not None
        await self._drop_connection()

        if reconnecting and self.reconnect_backoff_seconds:
            await asyncio.sleep(self.reconnect_backoff_seconds)

        if self._session is None:
            # ``total`` is deliberately unset: it would apply to the whole
            # exchange, and this socket is meant to outlive every one of its
            # frames. ``connect`` is what needs bounding here.
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=None, connect=self.connect_timeout_seconds
                )
            )

        try:
            ws = await self._session.ws_connect(self.url, headers=self._headers)
        except aiohttp.WSServerHandshakeError as exc:
            # The handshake is an HTTP response until it is not, so a refused
            # upgrade classifies exactly like a refused POST.
            failure = status_error(exc.status)
            logger.warning("Transcript handshake refused: %s", failure.code)
            # ``from None``: aiohttp's message names the URL it tried, and a
            # traceback is not somewhere the redaction filter reaches.
            raise failure from None
        except (aiohttp.ClientError, OSError) as exc:
            # ``OSError`` is not redundant: ``ConnectionResetError`` and
            # ``TimeoutError`` reach here without being ``ClientError``s.
            logger.warning("Transcript connect failed: %s", type(exc).__name__)
            raise BackendError("BACKEND_REQUEST_FAILED", retryable=True) from None

        self._ws = ws
        self._reader = asyncio.create_task(self._read_acks(ws))

    async def _flush(self) -> None:
        """Write every frame the current connection has not carried yet."""

        ws = self._ws
        if ws is None:  # pragma: no cover - _ensure_connection sets it or raises
            raise BackendError("BACKEND_REQUEST_FAILED", retryable=True)

        now = time.monotonic()
        for entry in list(self._pending.values()):
            if entry.written_at is not None:
                continue
            try:
                await ws.send_str(json.dumps(entry.frame, ensure_ascii=False))
            except (aiohttp.ClientError, OSError) as exc:
                logger.warning("Transcript send failed: %s", type(exc).__name__)
                raise BackendError("BACKEND_REQUEST_FAILED", retryable=True) from None
            entry.written_at = now

    async def _read_acks(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Clear acknowledged utterances until the socket ends.

        Runs as its own task, so it must not raise into the void: a failure is
        parked on ``_reader_failure`` and reported by the next
        :meth:`send` or :meth:`aclose`. Nothing here takes the lock - it only
        pops from ``_pending`` and sets an event, both single steps under one
        event loop - so a drop can await this task without waiting on itself.
        """

        try:
            async for message in ws:
                if message.type is not aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    frame = json.loads(message.data)
                except ValueError:
                    logger.warning("Transcript frame from Backend was not JSON")
                    continue
                if not isinstance(frame, dict) or frame.get("type") != FRAME_ACK:
                    continue
                utterance_id = frame.get("utteranceId")
                if isinstance(utterance_id, str):
                    self._pending.pop(utterance_id, None)
                    if not self._pending:
                        self._drained.set()
        except Exception as exc:  # noqa: BLE001 - parked, then reported
            # ``asyncio.CancelledError`` is a ``BaseException``, so a drop
            # cancelling this task does not land here.
            self._reader_failure = exc

    async def _drop_connection(self) -> None:
        """Forget the current socket and reader, and unmark what it carried."""

        reader, self._reader = self._reader, None
        ws, self._ws = self._ws, None

        if reader is not None:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader

        if ws is not None:
            with contextlib.suppress(aiohttp.ClientError, OSError):
                await ws.close()

        for entry in self._pending.values():
            entry.written_at = None

    def _ack_overdue(self) -> bool:
        """Whether the oldest written-but-unacknowledged frame has waited too long."""

        written = [
            entry.written_at
            for entry in self._pending.values()
            if entry.written_at is not None
        ]
        if not written:
            return False
        return time.monotonic() - min(written) > self.ack_timeout_seconds

    def _report_reader_failure(self) -> None:
        """Log and clear whatever stopped the reader task."""

        failure, self._reader_failure = self._reader_failure, None
        if failure is not None:
            # The type, not the message: an aiohttp exception's text can name
            # the Backend host, and this module's logger is not one the
            # redaction filter is attached to.
            logger.warning("Transcript ACK reader stopped: %s", type(failure).__name__)


def build_transcript_channel(settings: Settings, session_id: str) -> TranscriptChannel:
    """The transcript channel described by ``settings``, for one session.

    Raises rather than opening a channel aimed at an empty host, so a missing
    ``BACKEND_BASE_URL`` fails where the channel is built instead of when the
    first utterance is confirmed.
    """

    return TranscriptChannel(
        transcript_url(settings.backend_base_url, session_id),
        headers=auth_headers(settings.backend_api_key),
        ack_timeout_seconds=settings.transcript_ack_timeout_seconds,
        max_pending=settings.transcript_max_pending,
        reconnect_backoff_seconds=settings.transcript_reconnect_backoff_seconds,
        connect_timeout_seconds=settings.backend_timeout_seconds,
    )
