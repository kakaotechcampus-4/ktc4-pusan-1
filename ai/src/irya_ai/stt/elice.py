"""Elice STT client (TechSpec F2).

The endpoint is a BentoML prediction service, not an OpenAI-compatible one:
requests are multipart with a ``file`` part, ``language`` is a word
("korean") rather than an ISO code, and the response wraps the text:

    {"_result": {"status": "ok"}, "transcript": {"text": ..., "chunks": [...]}}

Every ``chunks`` entry observed from this deployment has carried a
segment-level span, and that is the service's own default rather than a
consequence of what these requests ask for: the deployment's OpenAPI schema
types ``return_timestamps`` as a boolean defaulting to ``true``, so the
cached corpus was produced with timestamps already enabled and still came
back as whole utterances. Elice's model-library page shows a word-level
example, but it passes the string ``'word'`` to a field this deployment
declares boolean, so the page's setting is not one this contract offers.
That last step is read off the schema, not tested: no request here has ever
carried ``return_timestamps`` in any form, so the deployment has never been
asked for word mode and has never refused it.
Requests therefore carry ``file``, ``model`` and ``language`` and nothing
else, and :mod:`irya_ai.stt.segmentation` does not overlap segments because
segment-level spans leave an overlap nothing to be de-duplicated by. The
counts behind that observation live with the STT bench data, which is kept
outside this repository.

Errors leave this module as :class:`SttError` carrying a stable ``code`` and
a ``retryable`` flag, and nothing else. Provider response bodies, transcript
text, API keys and the deployment URL never reach the message, because the
message is what gets logged - the same boundary
:class:`irya_ai.analysis.AnalysisError` draws for the LLM path.

That boundary covers what this module logs. It does not, by itself, cover
what ``httpx`` and ``httpcore`` log about the same request: they name the
deployment host in their own records, at INFO and DEBUG respectively.
:class:`EliceSttClient` closes that by registering its client's host with
:mod:`irya_ai.stt.http_logging`, which redacts the host out of those two
libraries' records and leaves everything else in the log alone. It happens in
the constructor, so it covers a client from :func:`build_client` and a client
the caller built and passed in equally. A caller that reaches the deployment
through some other HTTP library, or that logs the URL from its own code, is
outside this and has to redact that separate logging path itself.
"""

import asyncio
import dataclasses
import logging
import math
import time
from collections.abc import Mapping

import httpx

from irya_ai.stt.http_logging import protect_host

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "whisper-large-v3"
DEFAULT_LANGUAGE = "korean"

# A last timestamp this far past the end of the audio describes time that was
# never sent, which is a signal the text is untrustworthy - not proof of what
# the audio contained. Whisper answers near-silence with a stock sentence and
# stamps it with a full-window span, 29.98s for a 0.7s fragment, and that is
# the shape this number is cut to fit.
TIMESTAMP_TOLERANCE_MS = 500

# No interview segment is this long, so a span past it is a broken field
# rather than a late timestamp. The hallucination guard handles plausible
# overruns; this only rejects values that cannot be a time at all.
MAX_TIMESTAMP_SECONDS = 24 * 60 * 60

# HTTP statuses worth another attempt. Everything else 4xx is a request this
# client will keep getting wrong, so retrying it is a storm, not a recovery.
RETRYABLE_STATUSES = frozenset({408, 409, 425, 429})


class SttError(RuntimeError):
    """Transcription failed and the caller has no text to show.

    ``code`` is a stable identifier safe to log and to branch on; it is also
    the exception message. ``retryable`` says whether the same request could
    plausibly succeed later - a timeout can, a rejected key cannot.

    Nothing derived from the provider body, the transcript or the deployment
    URL belongs in here. Callers log ``code``; anything attached to it would
    be logged with it.
    """

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclasses.dataclass(frozen=True)
class Transcription:
    """One segment's result, with what is needed to judge whether to trust it.

    ``latency_ms`` is how long the caller waited, retries included, because
    that is what display lag is made of - not how fast one attempt was.
    """

    text: str
    span_end_ms: int | None
    latency_ms: int

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def _mapping(value: object, *, allow_missing: bool = True) -> Mapping:
    """A wrapper object, or an empty one when the field is simply absent.

    ``None`` and a missing key mean the same thing here and are tolerated -
    the service omits ``_result`` on some successful bodies. A field that is
    present as some *other* type is a shape this parser does not understand,
    which is a different thing from an absent one.
    """

    if value is None and allow_missing:
        return {}
    if not isinstance(value, Mapping):
        raise SttError("STT_MALFORMED_RESPONSE")
    return value


def _offset_seconds(value: object) -> float | None:
    """One end of a chunk's span: a finite second inside the session, or null.

    ``None`` is an answer, not an error. Whisper leaves the end of an unclosed
    trailing chunk null, and this parser does not require the start either, so
    a null either side means "this chunk carries no timing there". Anything
    present has to be a real time: a finite number, not a bool, and inside a
    range an interview could plausibly occupy.
    """

    if value is None:
        return None
    # bool is an int subclass and is never a timestamp.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SttError("STT_MALFORMED_RESPONSE")
    # Order matters. JSON integers are unbounded, and float(10 ** 400) - which
    # math.isfinite() does internally - raises OverflowError, a plain
    # ArithmeticError that would escape this boundary as surely as the
    # TypeErrors above it. Comparing an int against an int bound is exact at
    # any magnitude, so the range check runs first and rejects the huge value
    # before anything converts it. Only floats can be nan or inf, and for those
    # isfinite() never converts.
    if isinstance(value, float) and not math.isfinite(value):
        raise SttError("STT_MALFORMED_RESPONSE")
    if not 0 <= value <= MAX_TIMESTAMP_SECONDS:
        raise SttError("STT_MALFORMED_RESPONSE")
    # Bounded above, so this conversion cannot overflow.
    return float(value)


def _span_end_seconds(timestamp: object) -> float | None:
    """The end of one chunk's span, or ``None`` when it carries no timing.

    The documented shape is a pair, ``[start, end]``, and both ends are
    checked even though only the end is used: a chunk whose start is negative,
    non-numeric, or later than its end is not a span this parser understood,
    and taking its end anyway would put an invented number into a transcript.
    A pair that is the wrong length is malformed for the same reason.
    """

    if timestamp is None:
        return None
    if not isinstance(timestamp, list | tuple):
        raise SttError("STT_MALFORMED_RESPONSE")
    if len(timestamp) != 2:
        raise SttError("STT_MALFORMED_RESPONSE")

    start = _offset_seconds(timestamp[0])
    end = _offset_seconds(timestamp[1])
    if start is not None and end is not None and start > end:
        raise SttError("STT_MALFORMED_RESPONSE")
    return end


def parse_response(payload: object, *, latency_ms: int) -> Transcription:
    """Validate the wrapped response body and pull text and the last span out.

    This is the boundary: everything past it is trusted, so every shape the
    service could return has to be decided here. Anything unexpected leaves as
    :class:`SttError`, never as a ``TypeError`` or an ``IndexError`` escaping
    into a caller that is iterating a live stream.

    Absent text is an empty transcription, which the caller drops as ``EMPTY``.
    Text present as a non-string is malformed. The two are not the same answer
    and are not reported as the same thing.
    """

    body = _mapping(payload, allow_missing=False)

    result = _mapping(body.get("_result"))
    status = result.get("status")
    if status is not None and status != "ok":
        # The provider's own ``reason`` string is deliberately dropped: it is
        # free-form provider text and this message is logged.
        raise SttError("STT_PROVIDER_ERROR")

    transcript = _mapping(body.get("transcript"))

    text = transcript.get("text")
    if text is None:
        text = ""
    elif not isinstance(text, str):
        raise SttError("STT_MALFORMED_RESPONSE")

    chunks = transcript.get("chunks")
    if chunks is None:
        chunks = []
    elif not isinstance(chunks, list | tuple):
        raise SttError("STT_MALFORMED_RESPONSE")

    ends = []
    for chunk in chunks:
        end = _span_end_seconds(_mapping(chunk).get("timestamp"))
        if end is not None:
            ends.append(end)

    return Transcription(
        text=text.strip(),
        span_end_ms=round(max(ends) * 1000) if ends else None,
        latency_ms=latency_ms,
    )


def is_hallucinated(transcription: Transcription, audio_duration_ms: int) -> bool:
    """Whether the result's own timestamps run past the audio that was sent.

    A heuristic for one specific failure, not hallucination detection. It
    catches the case segmentation lets through - a segment holding a little
    speech and a lot of room tone, which comes back as a fluent sentence
    nobody said, stamped with a full-window span. A fabricated sentence
    stamped inside the real span passes this guard, and a result carrying no
    timings is never judged by it at all.
    """

    if transcription.span_end_ms is None:
        return False
    return transcription.span_end_ms > audio_duration_ms + TIMESTAMP_TOLERANCE_MS


def _status_error(status_code: int) -> SttError:
    """Classify an HTTP status into a typed error, without the body.

    Auth and client errors are permanent: the next identical request gets the
    identical answer, so retrying them is a storm against a deployment that is
    already saying no. Rate limits and server errors are the retryable ones.
    """

    if status_code in (401, 403):
        return SttError("STT_AUTH_FAILED", retryable=False)
    if status_code in RETRYABLE_STATUSES or status_code >= 500:
        return SttError("STT_REQUEST_FAILED", retryable=True)
    if 400 <= status_code < 500:
        return SttError("STT_CLIENT_ERROR", retryable=False)
    return SttError("STT_REQUEST_FAILED", retryable=True)


def _decode(response: httpx.Response) -> object:
    """JSON out of a 200, or a typed error.

    A gateway answering 200 with an HTML error page is the case this exists
    for: the status says success and the body is not JSON at all.
    """

    try:
        return response.json()
    except ValueError as exc:
        raise SttError("STT_MALFORMED_RESPONSE") from exc


class EliceSttClient:
    """Async client for one Elice STT deployment.

    The deployment scales to zero, so the first request after an idle period
    pays a cold start. Where it was observed during this work it ran to tens
    of seconds against a couple of seconds warm, but that is one author's
    measurement of one deployment, not a figure to plan against.
    :meth:`warm_up` tries to move that cost ahead of the interview rather than
    into it. It guarantees nothing: the deployment can scale back down between
    the warm-up and the first segment, and a later request can land on a
    worker this one never touched.

    Constructing one registers ``client.base_url``'s host with
    :func:`irya_ai.stt.http_logging.protect_host`, so the deployment host is
    kept out of the HTTP libraries' own log records for as long as the
    process runs. The client itself stays caller-owned: this does not close
    it, and it does not read its headers.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        model: str = DEFAULT_MODEL,
        language: str = DEFAULT_LANGUAGE,
        retries: int = 2,
        backoff_seconds: float = 1.0,
    ) -> None:
        # Checked here rather than discovered later: a negative ``retries``
        # makes the request loop run zero times and raise the placeholder
        # failure without ever calling the deployment, which reads exactly
        # like an outage.
        if retries < 0:
            raise ValueError("retries must not be negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")
        if not model:
            raise ValueError("model must not be empty")
        if not language:
            raise ValueError("language must not be empty")

        # Before the first request, because the leak this closes is ``httpx``
        # logging the request line as it sends it. Registering the host is
        # the whole contract: no key, no header, nothing the caller has to
        # remember to call.
        protect_host(client.base_url)

        self.client = client
        self.model = model
        self.language = language
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    async def transcribe(
        self, pcm_wav: bytes, *, filename: str = "segment.wav"
    ) -> Transcription:
        """Send one WAV-framed segment and return its transcription.

        Raises :class:`SttError` and nothing else. Retries only what could
        plausibly answer differently next time; a rejected key or a request
        this client builds wrong fails on the first attempt rather than three
        times over.
        """

        failure = SttError("STT_REQUEST_FAILED", retryable=True)
        started = time.perf_counter()
        for attempt in range(self.retries + 1):
            try:
                response = await self.client.post(
                    "/v1/audio/transcriptions",
                    files={"file": (filename, pcm_wav, "audio/wav")},
                    data={"model": self.model, "language": self.language},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                failure = _status_error(exc.response.status_code)
            except (httpx.HTTPError, httpx.InvalidURL):
                # Transport-level: timeouts, DNS, refused connections. All of
                # them can answer differently on the next attempt.
                failure = SttError("STT_REQUEST_FAILED", retryable=True)
            else:
                latency_ms = round((time.perf_counter() - started) * 1000)
                return parse_response(_decode(response), latency_ms=latency_ms)

            if not failure.retryable or attempt == self.retries:
                break
            await asyncio.sleep(self.backoff_seconds * 2**attempt)

        raise failure

    async def warm_up(self, probe: bytes) -> bool:
        """Try to take the cold start now. Returns whether it was answered.

        ``True`` means this one request succeeded, not that the next one will
        be fast: nothing here holds a worker open, and the deployment is free
        to scale down again or to route the interview somewhere else.
        """

        try:
            await self.transcribe(probe, filename="warmup.wav")
        except SttError as exc:
            logger.warning(
                "STT warm-up failed (%s); a cold start may still be ahead",
                exc.code,
            )
            return False
        return True


def build_http_client(
    settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """An ``AsyncClient`` aimed at the configured deployment.

    Raises when the deployment is not configured rather than sending requests
    to an empty host, so a missing ``ELICE_STT_BASE_URL`` fails at startup.
    """

    base_url = settings.elice_stt_base_url.rstrip("/")
    if not base_url:
        raise SttError("ELICE_STT_BASE_URL_NOT_SET")
    return httpx.AsyncClient(
        base_url=base_url,
        headers={
            "Authorization": f"Bearer {settings.elice_api_key.get_secret_value()}"
        },
        timeout=settings.elice_stt_timeout_seconds,
        transport=transport,
    )


def build_client(
    settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> EliceSttClient:
    """Assemble the STT client described by ``settings``."""

    return EliceSttClient(
        build_http_client(settings, transport=transport),
        model=settings.elice_stt_model,
        language=settings.elice_stt_language,
    )
