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
the next connection - a connection this module opens itself when Backend hangs
up, rather than leaving the frames parked until the next utterance is
confirmed.

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

# How long a socket being abandoned may spend on its closing handshake.
# aiohttp waits for Backend's CLOSE frame before ``ws.close()`` returns - ten
# seconds by default - and 3.14's ``close()`` takes no timeout argument, so the
# bound is set on the connection with ``ClientWSTimeout.ws_close`` and enforced
# again around the call. The socket is gone either way; the only thing at stake
# is how long the reconnect behind it has to wait.
CLOSE_TIMEOUT_SECONDS = 1.0

# How long one frame may spend reaching the transport. ``send_str`` is not the
# step it looks like: aiohttp pauses its writer while the transport's buffer is
# over the high-water mark, which is what a Backend that has stopped reading
# looks like from here, and the wait has no bound of its own. Deliberately not
# ``ack_timeout_seconds`` - that one is Backend's budget for answering and the
# tests shorten it on purpose, while this one is the socket's for accepting.
WRITE_TIMEOUT_SECONDS = 5.0

# The floor under the gap between two rounds of a background recovery. A
# connection that dies as fast as it opens would otherwise be reconnected in a
# hot loop; the reconnect backoff is what paces this in a real run, and this is
# what paces it when the channel is configured without one.
RECOVERY_MIN_INTERVAL_SECONDS = 0.05


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

    Not safe to share across sessions - one instance is one ``sessionId``.
    Concurrent sends from the STT pipeline serialise rather than interleave
    frames, under three locks that are deliberately not one, because each of
    them guards a different kind of wait:

    * the state lock covers the buffer, the socket and the reader task, and is
      only ever held across steps - never across network work, so that the
      media path can always buffer an utterance it has already confirmed;
    * the connect lock serialises opening a connection - the old socket's
      close, the reconnect backoff, the handshake - so a burst of sends on a
      dead channel opens one socket rather than one each;
    * the write lock serialises the frames going out on the current socket, so
      two flushes cannot interleave on one writer.
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
        # The reconnect a stopped reader starts on its own. At most one runs
        # at a time, and :meth:`aclose` is what ends it.
        self._recovery: asyncio.Task[None] | None = None
        # Raised by a reader that stops while a recovery is already running:
        # that recovery opened the socket which just died, so it is the one
        # that has to go round again rather than leave the notice unanswered.
        self._recovery_wanted = False
        # Sockets a cancelled :meth:`_discard` could not stay to close.
        self._abandoned: set[asyncio.Task[None]] = set()
        self._closed = False
        self._lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
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
        where an utterance is refused outright, and which is not raised until
        what is already buffered has had its own attempt at Backend.

        Cancellation is the exception to "nothing else": a cancel aimed at the
        caller travels out of here untouched, with the utterance buffered.

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

        # Checking the cap and taking the slot have to be the same critical
        # section. Concurrent sends that each read the buffer as one under the
        # cap and then each took a slot would settle above it, which is the
        # one number this buffer exists to hold.
        async with self._lock:
            # ``aclose`` sets this before it waits for the state lock. A send
            # may have passed the fast check above just before that happened,
            # so admission needs the same check inside the critical section or
            # shutdown can finish with a newly buffered, undeliverable frame.
            if self._closed:
                raise BackendError("BACKEND_TRANSCRIPT_CHANNEL_CLOSED", retryable=False)
            self._report_reader_failure()
            admitted = self._admit(utterance_id, frame)
            overdue = self._ack_overdue() if admitted else False

        if not admitted:
            # The cap is checked against a buffer that only Backend can
            # empty, so checking it before the connection is what would make
            # recovery impossible: Backend down long enough to fill the buffer
            # would mean every later utterance refused before a reconnect was
            # ever attempted, and the frames already held never written. They
            # get their attempt at the wire first, and only a genuinely new
            # utterance that is still over the cap afterwards is refused.
            await self._deliver_buffered()
            async with self._lock:
                if self._closed:
                    raise BackendError(
                        "BACKEND_TRANSCRIPT_CHANNEL_CLOSED", retryable=False
                    )
                admitted = self._admit(utterance_id, frame)
                overdue = self._ack_overdue() if admitted else False
            if not admitted:
                logger.warning(
                    "Transcript buffer full (%d unacknowledged); dropping utterance",
                    self.unacknowledged,
                )
                raise BackendError("BACKEND_TRANSCRIPT_BUFFER_FULL", retryable=False)

        if overdue:
            # The socket is open and Backend is not answering on it. That is
            # indistinguishable from a half-open connection from here, so it
            # is treated as one: drop it and let the reconnect below write
            # everything still pending onto the new socket.
            logger.warning("Transcript ACK overdue; reopening the channel")
            await self._drop_connection()

        await self._ensure_connection()
        try:
            await self._flush()
        except BackendError:
            # The socket was open a moment ago and the write did not land, so
            # it went stale between utterances - a Backend restart, an idle
            # timeout on something in between. One fresh connection, which
            # also rewrites everything still pending, and then the caller
            # hears about it. A refused *connect* is deliberately not retried
            # here: Backend being down is not something an immediate second
            # attempt changes, and this call is standing in the media path
            # while it waits.
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

        # Set first, so a reader ending from here on does not start a
        # reconnect behind the shutdown; this one is already on its way out.
        recovery, self._recovery = self._recovery, None
        self._recovery_wanted = False
        if recovery is not None:
            recovery.cancel()
            await asyncio.wait({recovery})

        async with self._lock:
            self._report_reader_failure()
            draining = bool(self._pending) and self._usable()

        if draining:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._drained.wait(), self.ack_timeout_seconds)

        if self._pending:
            logger.warning(
                "Transcript channel closing with %d utterance(s) unacknowledged",
                self.unacknowledged,
            )

        await self._drop_connection()

        # Sockets a cancelled drop handed off rather than abandon. Each is
        # already bounded by ``CLOSE_TIMEOUT_SECONDS``, so this waits for the
        # closes to finish instead of racing ``session.close`` against them.
        abandoned, self._abandoned = self._abandoned, set()
        if abandoned:
            await asyncio.wait(abandoned)

        async with self._lock:
            session, self._session = self._session, None
        if session is not None:
            await session.close()

    async def _ensure_connection(self) -> None:
        """Open the socket if there is not a usable one, and start its reader.

        Only one of these runs at a time - the connect lock, not the state
        lock, is what serialises them - and none of the waiting inside happens
        while the state lock is held, so a concurrent send or close is not
        queued behind the old socket's close, the backoff and the handshake
        one after another. The state lock is taken for the bookkeeping at each
        end of that, which is where "one connection" is actually decided.
        """

        if self._usable():
            return

        async with self._connect_lock:
            if self._usable():
                # Someone else's connect, while this one waited for the lock.
                return

            async with self._lock:
                reconnecting = self._session is not None
                ws, reader = self._detach()
            await self._discard(ws, reader)

            if reconnecting and self.reconnect_backoff_seconds:
                await asyncio.sleep(self.reconnect_backoff_seconds)

            async with self._lock:
                if self._session is None and not self._closed:
                    # ``total`` is deliberately unset: it would apply to the
                    # whole exchange, and this socket is meant to outlive
                    # every one of its frames. ``connect`` is what needs
                    # bounding here.
                    self._session = aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(
                            total=None, connect=self.connect_timeout_seconds
                        )
                    )
                session = self._session

            if self._closed or session is None or session.closed:
                # :meth:`aclose` took the session away while this waited.
                raise BackendError("BACKEND_TRANSCRIPT_CHANNEL_CLOSED", retryable=False)

            try:
                ws = await session.ws_connect(
                    self.url,
                    headers=self._headers,
                    timeout=aiohttp.ClientWSTimeout(ws_close=CLOSE_TIMEOUT_SECONDS),
                )
            except aiohttp.WSServerHandshakeError as exc:
                # The handshake is an HTTP response until it is not, so a
                # refused upgrade classifies exactly like a refused POST.
                failure = status_error(exc.status)
                logger.warning("Transcript handshake refused: %s", failure.code)
                # ``from None``: aiohttp's message names the URL it tried, and
                # a traceback is not somewhere the redaction filter reaches.
                raise failure from None
            except (aiohttp.ClientError, OSError) as exc:
                # ``OSError`` is not redundant: ``ConnectionResetError`` and
                # ``TimeoutError`` reach here without being ``ClientError``s.
                logger.warning("Transcript connect failed: %s", type(exc).__name__)
                raise BackendError("BACKEND_REQUEST_FAILED", retryable=True) from None

            # Until the install lands, this socket exists only as a local:
            # a cancel anywhere in here would drop the last reference to a
            # live connection, so every exit closes it.
            try:
                async with self._lock:
                    orphaned = self._closed
                    if not orphaned:
                        self._ws = ws
                        self._reader = asyncio.create_task(self._read_acks(ws))

                if orphaned:
                    # Closed while the handshake was in flight. Nothing is ever
                    # going to read this socket, so it does not get left open.
                    await self._close_socket(ws)
                    raise BackendError(
                        "BACKEND_TRANSCRIPT_CHANNEL_CLOSED", retryable=False
                    )
            except BaseException:
                if self._ws is not ws and not ws.closed:
                    self._abandon_socket(ws)
                raise

    async def _flush(self) -> None:
        """Write every frame the current connection has not carried yet.

        The write lock, not the state lock, is what keeps two of these from
        interleaving frames on aiohttp's one-per-socket writer. ``send_str``
        only looks like a step: the writer pauses while the transport's buffer
        is over its high-water mark, which is exactly what a Backend that has
        stopped reading looks like from here, and waiting for that under the
        state lock would hold up the close, the drop and every concurrent send
        behind a peer that may never come back.

        Frames go out in the order they were buffered - the snapshot is taken
        under the state lock, and ``_pending`` keeps insertion order across the
        in-place replacement a correction makes - and an entry is marked
        written only if the socket that carried it is still the current one.
        """

        async with self._write_lock:
            async with self._lock:
                ws = self._ws
                if ws is None:  # pragma: no cover - _ensure_connection sets it
                    raise BackendError("BACKEND_REQUEST_FAILED", retryable=True)
                queue = [
                    entry
                    for entry in self._pending.values()
                    if entry.written_at is None
                ]

            for entry in queue:
                async with self._lock:
                    if self._ws is not ws:
                        # Dropped underneath this flush. Every entry is already
                        # unmarked, so the reconnect is what carries them now;
                        # writing on the old socket would only be noise.
                        raise BackendError("BACKEND_REQUEST_FAILED", retryable=True)
                    if entry.written_at is not None:
                        continue
                    data = json.dumps(entry.frame, ensure_ascii=False)

                try:
                    await asyncio.wait_for(ws.send_str(data), WRITE_TIMEOUT_SECONDS)
                except TimeoutError:
                    # Checked before ``OSError`` catches it - ``TimeoutError``
                    # is one. The frame is half on the wire at best, so the
                    # socket is not reusable and does not get handed back.
                    logger.warning("Transcript send stalled; dropping the connection")
                    await self._drop_connection()
                    raise BackendError(
                        "BACKEND_REQUEST_FAILED", retryable=True
                    ) from None
                except (aiohttp.ClientError, OSError) as exc:
                    logger.warning("Transcript send failed: %s", type(exc).__name__)
                    await self._drop_connection()
                    raise BackendError(
                        "BACKEND_REQUEST_FAILED", retryable=True
                    ) from None

                async with self._lock:
                    if self._ws is ws:
                        entry.written_at = time.monotonic()

    async def _read_acks(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Clear acknowledged utterances until the socket ends.

        Runs as its own task, so it must not raise into the void: a failure is
        parked on ``_reader_failure`` and reported by the next
        :meth:`send` or :meth:`aclose`. Nothing here takes the lock - it only
        pops from ``_pending`` and sets an event, both single steps under one
        event loop - so a drop can await this task without waiting on itself.
        That stays true now that :meth:`_flush` waits outside the state lock:
        what it holds across its write is an entry it already has a reference
        to, never the mapping, so a pop here cannot land mid-iteration.

        This task ending is also the only notice the channel gets that Backend
        hung up: a socket the peer has closed is still ``closed is False`` to
        aiohttp until something calls ``close()`` on it, and a frame written
        into that window is accepted by the transport and carried nowhere. So
        the reader ending is what starts the reconnect, rather than the next
        utterance happening to notice - there may not be a next utterance for
        minutes, and the frames already buffered would wait all of it.
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
        finally:
            # ``is``, not ``is not None``: a deliberate drop clears ``_ws``
            # before it cancels this task, so the connection it replaces does
            # not also ask for a replacement of its own.
            if self._ws is ws:
                self._start_recovery()

    def _start_recovery(self) -> None:
        """Reconnect in the background, if there is anything left to deliver."""

        if self._closed or not self._pending:
            return
        # Raised before the single-flight check, not instead of it. A recovery
        # that is still running opened the socket that just died, so returning
        # here without the flag would drop the only notice of that death and
        # leave the buffer waiting for an utterance that may never come.
        self._recovery_wanted = True
        if self._recovery is not None and not self._recovery.done():
            return
        self._recovery = asyncio.create_task(self._recover())

    async def _recover(self) -> None:
        """The background half of a reconnect: nobody is awaiting this.

        Which is the whole reason it exists, and also why nothing escapes it -
        an exception here would be reported by the loop as never retrieved,
        long after the moment it belonged to.

        Goes round again only for a connection that was opened and then died,
        which is a full handshake's worth of work per round rather than a spin,
        and never sooner than ``RECOVERY_MIN_INTERVAL_SECONDS``. A round that
        ends in a refused *connect* raises no notice, so a Backend that is down
        stops this after one attempt rather than retrying it forever.
        """

        try:
            while not self._closed:
                # Cleared before the attempt, so a death during it counts.
                # Nothing between the check below and this task completing
                # awaits, so a notice can never fall into that gap.
                self._recovery_wanted = False
                await self._deliver_buffered()
                if self._closed or not self._pending or not self._recovery_wanted:
                    return
                await asyncio.sleep(RECOVERY_MIN_INTERVAL_SECONDS)
        except Exception as exc:  # noqa: BLE001 - nothing is awaiting this task
            logger.warning("Transcript recovery stopped: %s", type(exc).__name__)

    async def _deliver_buffered(self) -> None:
        """Give what is already buffered one attempt at Backend, failure and all.

        The callers are the two places where a failure is not the caller's to
        hear about: the background reconnect, which nobody is awaiting, and
        :meth:`send` clearing the way for a full buffer, where the error that
        matters is the one about the new utterance.
        """

        async with self._lock:
            if not self._pending:
                return
            overdue = self._ack_overdue()

        try:
            if overdue:
                await self._drop_connection()
            await self._ensure_connection()
            await self._flush()
        except BackendError as failure:
            logger.warning("Transcript buffer still undelivered: %s", failure.code)

    async def _drop_connection(self) -> None:
        """Forget the current socket and reader, and unmark what it carried."""

        async with self._lock:
            ws, reader = self._detach()
        await self._discard(ws, reader)

    def _detach(
        self,
    ) -> tuple[aiohttp.ClientWebSocketResponse | None, asyncio.Task[None] | None]:
        """Give up the current connection, under the state lock, without waiting.

        Clearing ``_ws`` here is what tells the reader its own ending was
        asked for. Everything that waits - the cancellation, the closing
        handshake - is :meth:`_discard`, outside the lock.
        """

        reader, self._reader = self._reader, None
        ws, self._ws = self._ws, None
        for entry in self._pending.values():
            entry.written_at = None
        return ws, reader

    async def _discard(
        self,
        ws: aiohttp.ClientWebSocketResponse | None,
        reader: asyncio.Task[None] | None,
    ) -> None:
        """Wait out a detached connection: stop its reader, close its socket."""

        try:
            if reader is not None:
                reader.cancel()
                # ``asyncio.wait`` rather than ``await reader``: it reports the
                # reader's cancellation by returning rather than by raising, so
                # it does not have to be suppressed - and suppressing it here
                # would also swallow a cancel aimed at whoever is calling,
                # which is a ``send`` or an ``aclose`` that must stay cancelled.
                await asyncio.wait({reader})

            if ws is not None:
                await self._close_socket(ws)
        except BaseException:
            # A cancel aimed at the caller travels on untouched - but ``_detach``
            # took this socket out of ``_ws`` before the cancel landed, so there
            # is nothing left that would ever close it. It finishes closing on a
            # task of its own rather than staying open until the session does.
            if ws is not None and not ws.closed:
                self._abandon_socket(ws)
            raise

    def _abandon_socket(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Close a socket nobody is left to wait for, on a task of its own.

        The handle is kept because the loop only holds a weak reference to a
        running task, and :meth:`aclose` waits for whatever is still here.
        """

        closer = asyncio.create_task(self._close_socket(ws))
        self._abandoned.add(closer)
        closer.add_done_callback(self._abandoned.discard)

    async def _close_socket(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Close one socket, bounded, and without anything to say if it fails."""

        with contextlib.suppress(TimeoutError, aiohttp.ClientError, OSError):
            # Belt and braces with ``ClientWSTimeout.ws_close``: that bound is
            # aiohttp's own and the version it lives in is a dependency range,
            # while this one is enforced here.
            await asyncio.wait_for(ws.close(), CLOSE_TIMEOUT_SECONDS)

    def _usable(self) -> bool:
        """Whether a frame written now would actually be carried.

        The reader is half of the answer, not a detail: it ends the moment
        Backend's CLOSE arrives, while ``ws.closed`` stays ``False`` until
        something closes the socket from this side.
        """

        return (
            self._ws is not None
            and not self._ws.closed
            and self._reader is not None
            and not self._reader.done()
        )

    def _admit(self, utterance_id: str, frame: dict[str, object]) -> bool:
        """Buffer this frame unless that would exceed the cap. Under the lock.

        Checking and taking the slot are one call because they have to be one
        critical section - the caller releases the lock immediately after, and
        two sends that each checked before either took a slot would both be
        admitted at the cap.

        A corrected FINAL for an utterance already buffered replaces it rather
        than counting against the cap: Backend upserts on
        ``(sessionId, utteranceId)``, and one row there is one entry here. The
        replacement keeps the original's place in ``_pending``, so a correction
        does not reorder what has not gone out yet.
        """

        replacing = utterance_id in self._pending
        if not replacing and len(self._pending) >= self.max_pending:
            return False

        self._pending[utterance_id] = _Pending(frame)
        self._drained.clear()
        return True

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
