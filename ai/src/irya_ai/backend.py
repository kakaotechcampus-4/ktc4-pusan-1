"""The Agent's client for the Backend's ``/internal/v1`` routes.

``/api/v1`` is the Frontend's; ``/internal/v1`` is this one, Backend to Agent
and back. The payloads it sends are in :mod:`irya_ai.schemas.wire`, which is
also where the Agent's own vocabulary is translated into the agreed one - this
module only carries what it is given.

It follows :class:`~irya_ai.stt.elice.EliceSttClient`: the base URL is
configuration rather than a constant, a missing one fails when the client is
built instead of when the interview starts, the host is registered with
:func:`~irya_ai.stt.http_logging.protect_host` so it stays out of the HTTP
libraries' own log records, and the client itself stays caller-owned.

What this deliberately does not decide: what happens after a send finally
fails. Whether the Agent buffers, replays or gives up is not agreed with
Backend yet, and guessing here would bury the choice in a retry loop.
:meth:`BackendClient.send` retries what can plausibly answer differently and
then raises, leaving the decision to its caller. A suggestion is the one case
with an easy answer already: a follow-up question that arrives after the
moment has passed is worse than one that never arrives, so dropping it is the
reasonable default.

Transcripts do not travel this way any more. The agreed contract moved them
onto a WebSocket, which is :mod:`irya_ai.transcripts`; Suggestion, Context and
Review stay here on HTTP. :meth:`BackendClient.send` is public rather than
private because it is the class's entry point, and every route method here is
the path it builds plus that one call.

The poller's three routes (#162, #176) read as well as write: the pending job
and the session context come back as JSON. They go through the same retry
loop (:meth:`BackendClient.request_json`), and a body that is not the JSON
the contract promises is ``BACKEND_MALFORMED_RESPONSE`` - not retried, since
the same bytes would come back again.
"""

import asyncio
import json
import logging
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from irya_ai.config import Settings
from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.jobs import PendingJob
from irya_ai.schemas.prep import PrepResult
from irya_ai.schemas.wire import SuggestionPayload
from irya_ai.stt.http_logging import protect_host

logger = logging.getLogger(__name__)

# Statuses under 500 that describe a moment rather than the request: the same
# bytes sent again later can be accepted. Everything else in the 4xx range is
# the Backend saying this request is wrong, which a retry does not change.
RETRYABLE_STATUSES = frozenset({408, 425, 429})


class BackendError(RuntimeError):
    """A call to the Backend did not land.

    ``code`` is a stable identifier safe to log and to branch on, and is also
    the exception message. ``retryable`` says whether the same call could
    plausibly succeed later. Nothing derived from the response body or the
    Backend URL belongs in here: callers log ``code``, and anything attached
    to it is logged with it.
    """

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class BackendClient:
    """Async client for one Backend deployment's internal API.

    Constructing one registers ``client.base_url``'s host for log redaction.
    The client is not closed here and its headers are not read.

    :mod:`irya_ai.transcripts` does not go through here - it holds a
    WebSocket, not an ``AsyncClient`` - but it classifies its handshake
    answers with the same :func:`status_error` and builds its path with the
    same :func:`path_segment`, so one status means one code across both.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        retries: int = 2,
        backoff_seconds: float = 0.5,
    ) -> None:
        if retries < 0:
            raise ValueError("retries must not be negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")

        protect_host(client.base_url)

        self.client = client
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    async def post_suggestion(
        self, session_id: str, payload: SuggestionPayload
    ) -> None:
        """Send one follow-up to ``POST .../sessions/{sessionId}/suggestions``.

        Raises :class:`BackendError` and nothing else, including
        ``BACKEND_INVALID_SESSION_ID`` for a session id that would rewrite the
        path - that one before any request goes out. What a final failure
        costs here is particular: a suggestion is only worth anything while
        the answer that prompted it is still on screen, so a caller that
        buffers one to replay later is buffering something that will arrive
        stale. Dropping it is the reasonable default.
        """

        await self.send(
            "POST",
            f"/internal/v1/sessions/{path_segment(session_id)}/suggestions",
            payload,
        )

    async def get_pending_job(self) -> PendingJob | None:
        """Ask ``GET /internal/v1/jobs/pending`` for the oldest waiting job.

        ``None`` when the queue is empty - Backend answers that with a 200 and
        a ``null`` body, not with a 404. Asking does not claim the job: until
        a result is put back, every call returns the same one (#165), which is
        why the poller works one job through before asking again.
        """

        body = await self.request_json("GET", "/internal/v1/jobs/pending")
        if body is None:
            return None
        try:
            return PendingJob.model_validate(body)
        except ValidationError:
            logger.warning("Backend pending job did not match the contract")
            raise BackendError("BACKEND_MALFORMED_RESPONSE", retryable=False) from None

    async def get_context(self, session_id: str) -> dict[str, Any]:
        """Read ``GET /internal/v1/sessions/{sessionId}/context`` as it is.

        Returned raw rather than as an :class:`InterviewContext`: the response
        carries the session's utterances alongside the context, and which of
        the two a caller wants is the caller's business (the prep poller
        drops them; a review job will need them). A body that is not a JSON
        object is ``BACKEND_MALFORMED_RESPONSE``.
        """

        body = await self.request_json(
            "GET", f"/internal/v1/sessions/{path_segment(session_id)}/context"
        )
        if not isinstance(body, dict):
            logger.warning("Backend context was not a JSON object")
            raise BackendError("BACKEND_MALFORMED_RESPONSE", retryable=False)
        return body

    async def put_prep(
        self, interview_id: str, result: PrepResult, *, requested_at: str
    ) -> None:
        """Store one preparation run at ``PUT .../interviews/{id}/prep``.

        The body is the :class:`PrepResult` as it stands plus ``requestedAt``
        copied from the job, which is how Backend matches the result to the
        request it answers. A ``BACKEND_CONFLICT`` (409) means a newer request
        replaced that one while this ran: the result is for a resume nobody
        has any more, and the right move is to drop it and ask for the next
        job, which will be the replacement.
        """

        body = result.model_dump(by_alias=True, mode="json")
        body["requestedAt"] = requested_at
        await self.request_json(
            "PUT",
            f"/internal/v1/interviews/{path_segment(interview_id)}/prep",
            body=body,
        )

    async def send(self, method: str, path: str, payload: CamelModel) -> None:
        """Send one payload to one ``/internal/v1`` route.

        Raises :class:`BackendError` and nothing else. Route- and payload-
        agnostic on purpose: the suggestion and review calls travel the same
        way and differ only in their model, so each route method is the path
        it builds plus this.
        """

        # ``by_alias`` is the whole point of the wire models - the agreed
        # contract is camelCase, and the field names are snake_case here.
        await self.request_json(
            method, path, body=payload.model_dump(by_alias=True, mode="json")
        )

    async def request_json(
        self, method: str, path: str, *, body: Any | None = None
    ) -> Any:
        """One ``/internal/v1`` call, retried, with its JSON body decoded.

        Returns ``None`` for an empty answer (a 204, or a 200 with nothing in
        it). Raises :class:`BackendError` and nothing else: a status is
        classified by :func:`status_error`, a transport failure retries, and
        a 2xx whose body is not JSON is ``BACKEND_MALFORMED_RESPONSE``.
        """

        failure = BackendError("BACKEND_REQUEST_FAILED", retryable=True)
        for attempt in range(self.retries + 1):
            try:
                response = await self.client.request(method, path, json=body)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                failure = status_error(exc.response.status_code)
            except (httpx.HTTPError, httpx.InvalidURL):
                # Transport-level: timeouts, DNS, refused connections. Every
                # one of them can answer differently on the next attempt.
                failure = BackendError("BACKEND_REQUEST_FAILED", retryable=True)
            else:
                return _decode(response)

            if not failure.retryable or attempt == self.retries:
                break
            await asyncio.sleep(self.backoff_seconds * 2**attempt)

        logger.warning("Backend call failed (%s %s): %s", method, path, failure.code)
        raise failure


def _decode(response: httpx.Response) -> Any:
    """The JSON of a 2xx answer, or ``None`` when there is no body to read."""

    if response.status_code == 204 or not response.content.strip():
        return None
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        # The body is Backend's and may hold anything; only the fact is logged.
        logger.warning("Backend answered 2xx with a body that is not JSON")
        raise BackendError("BACKEND_MALFORMED_RESPONSE", retryable=False) from None


def status_error(status_code: int) -> BackendError:
    """Classify an HTTP status into a typed error, without the body."""

    if 300 <= status_code < 400:
        # Internal API calls do not follow redirects. Repeating the same URL
        # cannot turn a route or slash mismatch into a success.
        return BackendError("BACKEND_CLIENT_ERROR", retryable=False)
    if status_code in (401, 403):
        return BackendError("BACKEND_AUTH_FAILED", retryable=False)
    if status_code == 409:
        # Backend's state moved on from what this request assumed. The same
        # bytes will be refused again; the caller has to re-read and decide.
        return BackendError("BACKEND_CONFLICT", retryable=False)
    if status_code in RETRYABLE_STATUSES or status_code >= 500:
        return BackendError("BACKEND_REQUEST_FAILED", retryable=True)
    if 400 <= status_code < 500:
        return BackendError("BACKEND_CLIENT_ERROR", retryable=False)
    return BackendError("BACKEND_REQUEST_FAILED", retryable=True)


def path_segment(value: str) -> str:
    """Refuse an id that would rewrite the path it is interpolated into.

    A session id arriving with a slash or a traversal in it would silently
    aim the request at a different route, and the Backend would answer about
    a session nobody asked for.

    It raises :class:`BackendError` - ``BACKEND_INVALID_SESSION_ID``, before
    any request goes out - which is the same type a rejected send raises. A
    caller looping over a session with a blanket ``except BackendError``
    around it will retry-or-drop a programming error as if Backend had
    answered.
    """

    segment = value.strip()
    if not segment or "/" in segment or segment in (".", ".."):
        raise BackendError("BACKEND_INVALID_SESSION_ID", retryable=False)
    return segment


def build_http_client(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """An ``AsyncClient`` aimed at the configured Backend.

    Raises when the Backend is not configured rather than sending requests to
    an empty host, so a missing ``BACKEND_BASE_URL`` fails at startup.
    """

    base_url = settings.backend_base_url.rstrip("/")
    if not base_url:
        raise BackendError("BACKEND_BASE_URL_NOT_SET", retryable=False)
    return httpx.AsyncClient(
        base_url=base_url,
        headers=auth_headers(settings.backend_api_key),
        timeout=settings.backend_timeout_seconds,
        transport=transport,
    )


def build_client(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> BackendClient:
    """Assemble the Backend client described by ``settings``."""

    return BackendClient(build_http_client(settings, transport=transport))


def auth_headers(api_key: SecretStr) -> dict[str, str]:
    """Bearer when a key is configured, nothing when it is not.

    How the Agent authenticates to ``/internal/v1`` is not settled with
    Backend yet. Sending an empty ``Authorization`` header would be worse than
    sending none - it reads as a client that thinks it authenticated - so an
    unset key means the header is simply absent, and local runs against a
    Backend that does not check one work without inventing a credential.
    """

    secret = api_key.get_secret_value()
    return {"Authorization": f"Bearer {secret}"} if secret else {}
