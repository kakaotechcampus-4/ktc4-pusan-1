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
then raises, leaving the decision to its caller.

Transcripts do not travel this way any more. The agreed contract moved them
onto a WebSocket, which is :mod:`irya_ai.transcripts`; Suggestion, Context and
Review stay here on HTTP. That leaves :class:`BackendClient` with no route
method of its own on this branch. :meth:`BackendClient.send` is public rather
than private because it is now the class's entry point, and the route methods
that call it - ``post_suggestion`` first - arrive in their own change.
"""

import asyncio
import logging

import httpx
from pydantic import SecretStr

from irya_ai.config import Settings
from irya_ai.schemas.base import CamelModel
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

    async def send(self, method: str, path: str, payload: CamelModel) -> None:
        """Send one payload to one ``/internal/v1`` route.

        Raises :class:`BackendError` and nothing else. Route- and payload-
        agnostic on purpose: the suggestion and review calls travel the same
        way and differ only in their model, so each route method is the path
        it builds plus this.
        """

        # ``by_alias`` is the whole point of the wire models - the agreed
        # contract is camelCase, and the field names are snake_case here.
        body = payload.model_dump(by_alias=True, mode="json")

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
                return

            if not failure.retryable or attempt == self.retries:
                break
            await asyncio.sleep(self.backoff_seconds * 2**attempt)

        logger.warning("Backend call failed (%s %s): %s", method, path, failure.code)
        raise failure


def status_error(status_code: int) -> BackendError:
    """Classify an HTTP status into a typed error, without the body."""

    if status_code in (401, 403):
        return BackendError("BACKEND_AUTH_FAILED", retryable=False)
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
