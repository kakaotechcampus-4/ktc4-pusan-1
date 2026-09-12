"""The Elice client: its wire format, its retries, and the hallucination guard."""

import httpx
import pytest

from irya_ai.config import Settings
from irya_ai.stt.elice import (
    TIMESTAMP_TOLERANCE_MS,
    EliceSttClient,
    SttError,
    Transcription,
    build_client,
    build_http_client,
    is_hallucinated,
    parse_response,
)

WAV = b"RIFF....WAVEfmt "


def body(text: str, chunks: list[list[float]] | None = None) -> dict:
    return {
        "_result": {"status": "ok", "reason": None},
        "transcript": {
            "text": text,
            "chunks": [
                {"timestamp": span, "text": text} for span in (chunks or [[0.0, 1.0]])
            ],
        },
    }


def client_for(handler, **kwargs) -> EliceSttClient:
    return EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid",
            transport=httpx.MockTransport(handler),
        ),
        backoff_seconds=0.0,
        **kwargs,
    )


def test_parse_response_reads_text_and_the_last_span_end() -> None:
    result = parse_response(
        body("안녕하세요", [[0.0, 1.5], [1.5, 3.92]]), latency_ms=800
    )

    assert result.text == "안녕하세요"
    assert result.span_end_ms == 3920
    assert result.latency_ms == 800
    assert not result.is_empty


def test_parse_response_without_chunks_has_no_span() -> None:
    result = parse_response(
        {"_result": {"status": "ok"}, "transcript": {"text": " 네 "}}, latency_ms=1
    )

    assert result.text == "네"
    assert result.span_end_ms is None


def test_parse_response_tolerates_a_missing_wrapper() -> None:
    assert parse_response({}, latency_ms=0).is_empty


def test_parse_response_raises_when_the_service_reports_failure() -> None:
    payload = {"_result": {"status": "error", "reason": "decode failed"}}

    with pytest.raises(SttError, match="decode failed"):
        parse_response(payload, latency_ms=0)


def test_hallucination_guard_catches_a_span_longer_than_the_audio() -> None:
    """Near-silence comes back as a stock sentence stamped with a full window."""

    stock = Transcription(
        text="시청해주셔서 감사합니다", span_end_ms=29980, latency_ms=900
    )

    assert is_hallucinated(stock, audio_duration_ms=1080)


@pytest.mark.parametrize("span_end_ms", [0, 2000, 2000 + TIMESTAMP_TOLERANCE_MS, None])
def test_hallucination_guard_passes_a_span_that_fits_the_audio(span_end_ms) -> None:
    """The tolerance absorbs rounding; a real result is never thrown away."""

    result = Transcription(text="네 맞습니다", span_end_ms=span_end_ms, latency_ms=900)

    assert not is_hallucinated(result, audio_duration_ms=2000)


async def test_transcribe_sends_multipart_with_the_service_field_names() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body("실시간 자막입니다"))

    result = await client_for(handler).transcribe(WAV, filename="seg_0007.wav")

    assert result.text == "실시간 자막입니다"
    request = seen[0]
    assert request.url.path == "/v1/audio/transcriptions"
    assert request.headers["content-type"].startswith("multipart/form-data")
    payload = request.content.decode("utf-8", "replace")
    assert 'name="file"; filename="seg_0007.wav"' in payload
    # The service takes a language word, not an ISO code.
    assert "korean" in payload
    assert "whisper-large-v3" in payload


async def test_transcribe_retries_then_succeeds() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=body("세 번째에 성공"))

    result = await client_for(handler).transcribe(WAV)

    assert result.text == "세 번째에 성공"
    assert len(attempts) == 3


async def test_transcribe_gives_up_after_the_last_attempt() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(500)

    with pytest.raises(SttError):
        await client_for(handler, retries=1).transcribe(WAV)

    assert len(attempts) == 2


async def test_warm_up_reports_failure_instead_of_raising() -> None:
    """A failed warm-up costs latency later; it must not stop the interview."""

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    def working(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body(""))

    assert await client_for(failing, retries=0).warm_up(WAV) is False
    assert await client_for(working, retries=0).warm_up(WAV) is True


def test_build_http_client_refuses_an_unconfigured_deployment() -> None:
    with pytest.raises(SttError, match="ELICE_STT_BASE_URL"):
        build_http_client(Settings(_env_file=None))


def test_build_client_carries_settings_onto_the_client() -> None:
    settings = Settings(
        _env_file=None,
        elice_stt_base_url="https://stt.invalid/",
        elice_api_key="unit-test-token",
        elice_stt_model="whisper-large-v3",
        elice_stt_language="korean",
    )

    client = build_client(
        settings, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )

    assert client.model == "whisper-large-v3"
    assert client.language == "korean"
    assert str(client.client.base_url) == "https://stt.invalid"
    assert client.client.headers["authorization"] == "Bearer unit-test-token"
