"""Elice STT client (TechSpec F2).

The endpoint is a BentoML prediction service, not an OpenAI-compatible one:
requests are multipart with a ``file`` part, ``language`` is a word
("korean") rather than an ISO code, and the response wraps the text:

    {"_result": {"status": "ok"}, "transcript": {"text": ..., "chunks": [...]}}

``chunks`` carry segment-level spans only. Word-level timings are not
available, which is why overlapping requests cannot be de-duplicated and why
:mod:`irya_ai.stt.segmentation` does not overlap them.
"""

import asyncio
import dataclasses
import logging
import time

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "whisper-large-v3"
DEFAULT_LANGUAGE = "korean"

# A response whose last timestamp runs this far past the audio did not come
# from the audio. Whisper answers near-silence with a stock sentence and
# stamps it with a full-window span - 29.98s for a 0.7s fragment.
TIMESTAMP_TOLERANCE_MS = 500


class SttError(RuntimeError):
    """Transcription failed and the caller has no text to show."""


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


def parse_response(payload: dict, *, latency_ms: int) -> Transcription:
    """Pull text and the last timestamp out of the wrapped response body."""

    result = payload.get("_result") or {}
    if result.get("status") not in (None, "ok"):
        raise SttError(f"STT reported {result.get('status')}: {result.get('reason')}")

    transcript = payload.get("transcript") or {}
    ends = [
        chunk["timestamp"][1]
        for chunk in transcript.get("chunks") or []
        if chunk.get("timestamp") and chunk["timestamp"][1] is not None
    ]
    return Transcription(
        text=(transcript.get("text") or "").strip(),
        span_end_ms=round(max(ends) * 1000) if ends else None,
        latency_ms=latency_ms,
    )


def is_hallucinated(transcription: Transcription, audio_duration_ms: int) -> bool:
    """Whether the result describes more audio than was actually sent.

    This is the last guard. Segmentation already refuses to send silence, so
    this catches what gets through: a segment that holds a little speech and a
    lot of room tone, which comes back as a fluent sentence nobody said.
    """

    if transcription.span_end_ms is None:
        return False
    return transcription.span_end_ms > audio_duration_ms + TIMESTAMP_TOLERANCE_MS


class EliceSttClient:
    """Async client for one Elice STT deployment.

    The deployment scales to zero, so the first request after an idle period
    takes 20-30s against 2-3s warm. :meth:`warm_up` pays that cost before an
    interview starts instead of inside it.
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
        self.client = client
        self.model = model
        self.language = language
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    async def transcribe(
        self, pcm_wav: bytes, *, filename: str = "segment.wav"
    ) -> Transcription:
        """Send one WAV-framed segment and return its transcription."""

        last_error: Exception | None = None
        started = time.perf_counter()
        for attempt in range(self.retries + 1):
            try:
                response = await self.client.post(
                    "/v1/audio/transcriptions",
                    files={"file": (filename, pcm_wav, "audio/wav")},
                    data={"model": self.model, "language": self.language},
                )
                response.raise_for_status()
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                last_error = exc
                if attempt == self.retries:
                    break
                await asyncio.sleep(self.backoff_seconds * 2**attempt)
                continue
            latency_ms = round((time.perf_counter() - started) * 1000)
            return parse_response(response.json(), latency_ms=latency_ms)

        raise SttError(
            f"STT request failed after {self.retries + 1} attempts"
        ) from last_error

    async def warm_up(self, probe: bytes) -> bool:
        """Take the cold start now. Returns whether the deployment answered."""

        try:
            await self.transcribe(probe, filename="warmup.wav")
        except SttError:
            logger.warning(
                "STT warm-up failed; the first real request will pay cold start"
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
        raise SttError("ELICE_STT_BASE_URL is not set")
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
