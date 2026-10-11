"""Elice STT client (TechSpec F2).

The endpoint is vLLM's OpenAI-compatible server (since 2026-10-06, #159):
``POST /v1/audio/transcriptions`` takes a multipart ``file`` with ``model``
and an ISO 639-1 ``language`` (``"ko"``), and answers in the OpenAI shape.
The default ``json`` body is text alone; this client always asks for
``response_format=verbose_json`` because the hallucination guard needs the
timing that only that shape carries:

    {"text": ..., "duration": ..., "language": ...,
     "segments": [{"id": 0, "start": 0.0, "end": 4.78, "text": ...}, ...],
     "words": []}

``segments`` are sentence-sized, the same granularity the previous BentoML
deployment reported as ``chunks[].timestamp``, so the no-overlap strategy in
:mod:`irya_ai.stt.segmentation` carries over unchanged. ``words`` has come
back empty on every request so far, including with
``timestamp_granularities[]=word``, so nothing here reads it. The schema also
offers ``prompt`` (a vocabulary hint) and ``stream``; neither is sent yet -
both are their own decision (#159).

The previous deployment answered ``{"_result": {"status"}, "transcript":
{"text", "chunks"}}`` with ``language="korean"``. That shape is gone and is
not parsed any more: a body in it reads as an empty transcription, which is
exactly how the swap was noticed, so :func:`parse_response` refuses a body
with no ``text`` key rather than treating it as silence.

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
import re
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime

import httpx

from irya_ai.stt.circuit import Admission, CircuitBreaker
from irya_ai.stt.http_logging import protect_host

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "whisper-large-v3"
# ISO 639-1, as the OpenAI transcription API defines ``language``. The old
# deployment wanted the word "korean"; the new one accepts that too but the
# result is indistinguishable from auto-detection, so the documented form is
# the one sent.
DEFAULT_LANGUAGE = "ko"
# Only ``verbose_json`` carries ``segments`` and their spans. Without them the
# hallucination guard has nothing to judge.
RESPONSE_FORMAT = "verbose_json"

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

# What Whisper learned from subtitle credits and channel outros, and says over
# room tone. The timestamp guard catches it when the span runs past the audio;
# these catch it when the span happens to fit. Each is a whole-utterance
# match, never a substring: nobody in an interview thanks anyone for watching
# or asks for a subscription, but they do say "감사합니다", and a sentence that
# merely contains one of these is speech. Written without spaces or
# punctuation, because that is what comparison strips.
STOCK_PHRASES = (
    "시청해주셔서감사합니다",
    "시청해주셔서고맙습니다",
    "끝까지시청해주셔서감사합니다",
    "오늘도시청해주셔서감사합니다",
    "구독과좋아요부탁드립니다",
    "구독과좋아요알림설정부탁드립니다",
    "구독좋아요알림설정부탁드립니다",
    "좋아요와구독부탁드립니다",
    "다음영상에서만나요",
    "다음영상에서뵙겠습니다",
    "자막제공및자막편집",
)
# A broadcast sign-off, "MBC 뉴스 홍길동입니다": the reporter's name varies,
# which is why it is a pattern and not one more phrase.
_NEWS_SIGNOFF = r"(?:MBC|KBS|SBS|YTN|JTBC)뉴스[가-힣]{2,4}입니다"
# One or more stock pieces back to back and nothing else - Whisper chains them
# ("시청해 주셔서 감사합니다. 구독과 좋아요 부탁드립니다.").
_STOCK_TEXT = re.compile(
    "(?:" + "|".join([*map(re.escape, STOCK_PHRASES), _NEWS_SIGNOFF]) + ")+"
)
# Everything comparison ignores: whitespace, punctuation, symbols. Hangul and
# Latin letters are word characters and survive.
_NOT_A_LETTER = re.compile(r"[\W_]+")

# HTTP statuses worth another attempt. Everything else 4xx is a request this
# client will keep getting wrong, so retrying it is a storm, not a recovery.
RETRYABLE_STATUSES = frozenset({408, 409, 425, 429})

# The longest ``Retry-After`` worth waiting out. A deployment asking for more
# is not coming back within a live caption's lifetime, so the request fails
# now rather than sleeping into a result nobody will read - and retrying
# sooner than it asked would only add to the load it is shedding.
MAX_RETRY_AFTER_SECONDS = 10.0


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

    ``None`` and a missing key mean the same thing here and are tolerated. A
    field that is present as some *other* type is a shape this parser does
    not understand, which is a different thing from an absent one.
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


def _segment_end_seconds(segment: object) -> float | None:
    """The end of one segment's span, or ``None`` when it carries no timing.

    A segment is an object with ``start`` and ``end`` in seconds. Both are
    checked even though only the end is used: a segment whose start is
    negative, non-numeric, or later than its end is not a span this parser
    understood, and taking its end anyway would put an invented number into a
    transcript. A segment that is not an object at all is malformed for the
    same reason; one with a null end simply carries no timing.
    """

    fields = _mapping(segment)
    start = _offset_seconds(fields.get("start"))
    end = _offset_seconds(fields.get("end"))
    if start is not None and end is not None and start > end:
        raise SttError("STT_MALFORMED_RESPONSE")
    return end


def parse_response(payload: object, *, latency_ms: int) -> Transcription:
    """Validate the ``verbose_json`` body and pull text and the last span out.

    This is the boundary: everything past it is trusted, so every shape the
    service could return has to be decided here. Anything unexpected leaves as
    :class:`SttError`, never as a ``TypeError`` or an ``IndexError`` escaping
    into a caller that is iterating a live stream.

    ``text`` is required. A transcription body without it is not "nothing was
    said" - the service always writes the key, empty or not - it is a body in
    some other shape, and reading it as silence is how a whole interview's
    captions went missing when the deployment changed (#159). An empty string
    *is* silence, which the caller drops as ``EMPTY``. Absent segments mean
    the hallucination guard has nothing to judge, which is an answer too.

    An ``error`` object is the provider saying no inside a 200. Its message
    is free-form provider text and is deliberately not forwarded.
    """

    body = _mapping(payload, allow_missing=False)

    if body.get("error") is not None:
        raise SttError("STT_PROVIDER_ERROR")

    text = body.get("text")
    if not isinstance(text, str):
        raise SttError("STT_MALFORMED_RESPONSE")

    segments = body.get("segments")
    if segments is None:
        segments = []
    elif not isinstance(segments, list | tuple):
        raise SttError("STT_MALFORMED_RESPONSE")

    ends = []
    for segment in segments:
        end = _segment_end_seconds(segment)
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


def is_stock_phrase(text: str) -> bool:
    """Whether the whole text is one of Whisper's stock outros and nothing else.

    The other half of :func:`is_hallucinated`, for the fabricated sentence
    stamped inside the real span. Only the exact training-data credits are
    recognised, so speech that uses the same words is never thrown away.
    """

    letters = _NOT_A_LETTER.sub("", text)
    return bool(letters) and _STOCK_TEXT.fullmatch(letters) is not None


# Failures that say the deployment is unwell, as opposed to this one request
# being wrong (``STT_CLIENT_ERROR``) or this client being closed. A malformed
# body counts: a gateway answering 200 with an error page is an outage.
_BREAKER_FAILURES = frozenset(
    {
        "STT_AUTH_FAILED",
        "STT_REQUEST_FAILED",
        "STT_MALFORMED_RESPONSE",
        "STT_PROVIDER_ERROR",
    }
)


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


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """The wait a 429 or 503 asked for, or ``None`` when it asked for none.

    Both forms RFC 9110 allows: delay-seconds and an HTTP-date. A header that
    is neither is ignored rather than trusted, and a date already past is no
    wait at all.
    """

    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return None
    if value.isascii() and value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        return None
    return max(0.0, when.timestamp() - time.time())


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

    ``breaker`` is off unless passed. The live path wants it: a deployment
    that has stopped answering otherwise holds every segment for its full
    deadline. A batch caller that can afford to wait for each segment does
    not, because fail-fast would drop segments a retry would have recovered.
    See :mod:`irya_ai.stt.circuit` for what it counts and what it costs.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        model: str = DEFAULT_MODEL,
        language: str = DEFAULT_LANGUAGE,
        retries: int = 2,
        backoff_seconds: float = 1.0,
        breaker: CircuitBreaker | None = None,
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
        self.breaker = breaker

    async def transcribe(
        self, pcm_wav: bytes, *, filename: str = "segment.wav"
    ) -> Transcription:
        """Send one WAV-framed segment and return its transcription.

        Raises :class:`SttError` and nothing else. Retries only what could
        plausibly answer differently next time; a rejected key or a request
        this client builds wrong fails on the first attempt rather than three
        times over. With a breaker that is open, raises ``STT_CIRCUIT_OPEN``
        without sending.
        """

        breaker = self.breaker
        if breaker is None:
            return await self._send(pcm_wav, filename=filename, retries=self.retries)

        admission = breaker.admit()
        if admission is Admission.REFUSE:
            raise SttError("STT_CIRCUIT_OPEN", retryable=True)
        probe = admission is Admission.PROBE
        settled = False
        try:
            # A probe asks once: its job is a verdict, and retrying a
            # deployment that is already known to be failing is the storm
            # the breaker exists to stop.
            result = await self._send(
                pcm_wav, filename=filename, retries=0 if probe else self.retries
            )
        except SttError as exc:
            if exc.code in _BREAKER_FAILURES:
                breaker.record_failure(trip=exc.code == "STT_AUTH_FAILED")
                settled = True
            raise
        else:
            breaker.record_success()
            settled = True
            return result
        finally:
            # Cancelled - by the stream's deadline or by its close - or
            # refused for a reason that says nothing about the deployment.
            # The slot has to come back either way. A deadline is still
            # counted, by the stream, through :meth:`note_deadline_exceeded`.
            if probe and not settled:
                breaker.release_probe()

    def note_deadline_exceeded(self) -> None:
        """Count a call the caller gave up on as a failure of the deployment.

        The stream bounds each request with its own deadline, shorter than
        the HTTP timeout, so a deployment that accepts the connection and
        never answers is seen here only as a cancellation - and a
        cancellation from closing the stream looks the same from inside.
        The caller knows which it was; this is how it says so.
        """

        if self.breaker is not None:
            self.breaker.record_failure()

    async def _send(
        self, pcm_wav: bytes, *, filename: str, retries: int
    ) -> Transcription:
        failure = SttError("STT_REQUEST_FAILED", retryable=True)
        started = time.perf_counter()
        for attempt in range(retries + 1):
            asked: float | None = None
            try:
                response = await self.client.post(
                    "/v1/audio/transcriptions",
                    files={"file": (filename, pcm_wav, "audio/wav")},
                    data={
                        "model": self.model,
                        "language": self.language,
                        "response_format": RESPONSE_FORMAT,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                failure = _status_error(exc.response.status_code)
                asked = _retry_after_seconds(exc.response)
            except (httpx.HTTPError, httpx.InvalidURL):
                # Transport-level: timeouts, DNS, refused connections. All of
                # them can answer differently on the next attempt.
                failure = SttError("STT_REQUEST_FAILED", retryable=True)
            except RuntimeError:
                # ``httpx`` refuses to send on a closed client with a bare
                # ``RuntimeError``, which would otherwise leave as something
                # other than an :class:`SttError` and end the caller's track.
                # Nothing will send on that client again, so it is final.
                raise SttError("STT_CLIENT_CLOSED") from None
            else:
                latency_ms = round((time.perf_counter() - started) * 1000)
                return parse_response(_decode(response), latency_ms=latency_ms)

            if not failure.retryable or attempt == retries:
                break
            if asked is not None and asked > MAX_RETRY_AFTER_SECONDS:
                break
            # Another call has opened the breaker meanwhile: this one's
            # retries would be the requests the breaker is there to stop.
            if self.breaker is not None and self.breaker.is_open:
                break
            await asyncio.sleep(max(self.backoff_seconds * 2**attempt, asked or 0.0))

        raise failure

    async def warm_up(self, probe: bytes) -> bool:
        """Try to take the cold start now. Returns whether it was answered.

        ``True`` means this one request succeeded, not that the next one will
        be fast: nothing here holds a worker open, and the deployment is free
        to scale down again or to route the interview somewhere else.
        """

        # Around the breaker rather than through it: the deployment scales
        # to zero, so a warm-up failing is expected, and it must not leave
        # the breaker part-way to open before the interview has started.
        try:
            await self._send(probe, filename="warmup.wav", retries=self.retries)
        except SttError as exc:
            logger.warning(
                "STT warm-up failed (%s); a cold start may still be ahead",
                exc.code,
            )
            return False
        if self.breaker is not None:
            self.breaker.record_success()
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
    settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    breaker: CircuitBreaker | None = None,
) -> EliceSttClient:
    """Assemble the STT client described by ``settings``."""

    return EliceSttClient(
        build_http_client(settings, transport=transport),
        model=settings.elice_stt_model,
        language=settings.elice_stt_language,
        breaker=breaker,
    )
