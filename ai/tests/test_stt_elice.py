"""The Elice client: its wire format, its retries, and the hallucination guard."""

import asyncio

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

# An integer JSON can carry and a float cannot hold. Converting it - which
# ``math.isfinite`` does - raises ``OverflowError``.
HUGE = 10**400


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

    with pytest.raises(SttError) as caught:
        parse_response(payload, latency_ms=0)

    assert caught.value.code == "STT_PROVIDER_ERROR"


def test_the_provider_reason_never_reaches_the_error_that_gets_logged() -> None:
    """``reason`` is free-form provider text and the error message is logged.

    It is the one field in the body that carries whatever the deployment felt
    like saying, which is why it is the one field that must not ride out on an
    exception that ends up in a log line.
    """

    canary = "SYNTHETIC_PRIVATE_RESPONSE_MARKER"
    payload = {"_result": {"status": "error", "reason": canary}}

    with pytest.raises(SttError) as caught:
        parse_response(payload, latency_ms=0)

    assert canary not in str(caught.value)
    assert canary not in repr(caught.value.args)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="list_root"),
        pytest.param("plain text", id="string_root"),
        pytest.param({"transcript": []}, id="transcript_is_a_list"),
        pytest.param({"_result": "ok"}, id="result_is_a_string"),
        pytest.param({"transcript": {"text": 12}}, id="text_is_a_number"),
        pytest.param({"transcript": {"chunks": {}}}, id="chunks_is_a_mapping"),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [0]}]}},
            id="one_element_timestamp",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [0, 1, 2]}]}},
            id="three_element_timestamp",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [0, "x"]}]}},
            id="timestamp_is_a_string",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [0, True]}]}},
            id="timestamp_is_a_bool",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [0, -1.0]}]}},
            id="negative_timestamp",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [0, 1e12]}]}},
            id="timestamp_past_any_interview",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": "0,1"}]}},
            id="timestamp_is_a_string_pair",
        ),
        # The start is checked too, even though only the end is used: a span
        # whose start makes no sense is not a span whose end can be trusted.
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [-1.0, 2.0]}]}},
            id="negative_start",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": ["0.0", 2.0]}]}},
            id="start_is_a_string",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [True, 2.0]}]}},
            id="start_is_a_bool",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [1e12, 2.0]}]}},
            id="start_past_any_interview",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [3.0, 2.0]}]}},
            id="start_after_end",
        ),
        pytest.param(
            {
                "transcript": {
                    "text": "안녕",
                    "chunks": [{"timestamp": [float("nan"), 2.0]}],
                }
            },
            id="start_is_not_a_number",
        ),
        # JSON integers have no upper bound, and Python parses them at full
        # precision. Anything that converts one of these to a float - which
        # includes ``math.isfinite`` - raises ``OverflowError``, so the
        # magnitude has to be refused before any conversion touches it.
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [0, HUGE]}]}},
            id="end_is_too_large_for_a_float",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [HUGE, 1]}]}},
            id="start_is_too_large_for_a_float",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [0, -HUGE]}]}},
            id="end_is_too_negative_for_a_float",
        ),
        pytest.param(
            {"transcript": {"text": "안녕", "chunks": [{"timestamp": [-HUGE, 1]}]}},
            id="start_is_too_negative_for_a_float",
        ),
    ],
)
def test_a_malformed_body_becomes_a_typed_error_not_a_type_error(payload) -> None:
    """The boundary owns every shape, so nothing else has to guess at one.

    Each of these used to escape as ``AttributeError``, ``IndexError`` or
    ``TypeError`` into a caller iterating a live stream, which killed the
    iteration outright.
    """

    with pytest.raises(SttError) as caught:
        parse_response(payload, latency_ms=0)

    assert caught.value.code == "STT_MALFORMED_RESPONSE"
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    ("payload", "text", "span_end_ms"),
    [
        pytest.param({}, "", None, id="empty_body"),
        pytest.param({"transcript": None}, "", None, id="null_transcript"),
        pytest.param({"_result": None, "transcript": {}}, "", None, id="null_result"),
        pytest.param(
            {"transcript": {"text": "네", "chunks": None}}, "네", None, id="null_chunks"
        ),
        pytest.param(
            {"transcript": {"text": "네", "chunks": [{"timestamp": None}]}},
            "네",
            None,
            id="chunk_without_timing",
        ),
        pytest.param(
            {"transcript": {"text": "네", "chunks": [{"timestamp": [0.0, None]}]}},
            "네",
            None,
            id="unclosed_trailing_chunk",
        ),
        pytest.param(
            {"transcript": {"text": "네", "chunks": [{"timestamp": [0, 2]}]}},
            "네",
            2000,
            id="integer_timestamp",
        ),
        # A null start is allowed for the same reason a null end is: this
        # parser reads the end, and says so rather than requiring a start it
        # has no use for.
        pytest.param(
            {"transcript": {"text": "네", "chunks": [{"timestamp": [None, 2.0]}]}},
            "네",
            2000,
            id="chunk_without_a_start",
        ),
        pytest.param(
            {"transcript": {"text": "네", "chunks": [{"timestamp": [2.0, 2.0]}]}},
            "네",
            2000,
            id="an_instant_is_a_span",
        ),
    ],
)
def test_an_absent_field_is_an_answer_and_not_a_malformed_body(
    payload, text, span_end_ms
) -> None:
    """A field the service omits is a shape this parser understands.

    Absent text means nothing was said, which the stream drops as ``EMPTY``.
    Absent timings mean the hallucination guard has nothing to judge. Neither
    is a provider failure, and conflating them with one would turn a normal
    quiet segment into an error.
    """

    result = parse_response(payload, latency_ms=0)

    assert result.text == text
    assert result.span_end_ms == span_end_ms


async def test_a_success_status_with_a_non_json_body_is_a_typed_error() -> None:
    """A gateway can answer 200 with an HTML error page."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>upstream unavailable</html>")

    with pytest.raises(SttError) as caught:
        await client_for(handler, retries=0).transcribe(WAV)

    assert caught.value.code == "STT_MALFORMED_RESPONSE"


async def test_warm_up_survives_a_malformed_body() -> None:
    """Warm-up reports failure for every failure, not just for HTTP ones."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    assert await client_for(handler, retries=0).warm_up(WAV) is False


async def test_warm_up_survives_an_unbounded_integer_timestamp() -> None:
    """The overflow used to come out of warm-up as ``OverflowError``.

    Warm-up is called before a session starts, so an escape here takes the
    session down before any audio has been sent.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transcript": {
                    "text": "안녕",
                    "chunks": [{"timestamp": [0, HUGE]}],
                }
            },
        )

    assert await client_for(handler, retries=0).warm_up(WAV) is False


@pytest.mark.parametrize(
    ("status", "code", "attempts"),
    [
        pytest.param(401, "STT_AUTH_FAILED", 1, id="unauthorized"),
        pytest.param(403, "STT_AUTH_FAILED", 1, id="forbidden"),
        pytest.param(400, "STT_CLIENT_ERROR", 1, id="bad_request"),
        pytest.param(404, "STT_CLIENT_ERROR", 1, id="not_found"),
        pytest.param(422, "STT_CLIENT_ERROR", 1, id="unprocessable"),
        pytest.param(429, "STT_REQUEST_FAILED", 3, id="rate_limited"),
        pytest.param(500, "STT_REQUEST_FAILED", 3, id="server_error"),
        pytest.param(503, "STT_REQUEST_FAILED", 3, id="unavailable"),
    ],
)
async def test_only_a_failure_that_could_answer_differently_is_retried(
    status, code, attempts
) -> None:
    """Retrying a rejected key is a storm, not a recovery."""

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    with pytest.raises(SttError) as caught:
        await client_for(handler, retries=2).transcribe(WAV)

    assert caught.value.code == code
    assert len(seen) == attempts


async def test_a_transport_failure_is_retryable() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(SttError) as caught:
        await client_for(handler, retries=1).transcribe(WAV)

    assert caught.value.code == "STT_REQUEST_FAILED"
    assert caught.value.retryable is True
    assert len(seen) == 2


async def test_a_cancelled_request_is_not_reported_as_a_provider_failure() -> None:
    """Cancellation is the caller leaving, not the deployment failing."""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return httpx.Response(200, json=body("도달하지 않음"))

    task = asyncio.ensure_future(client_for(handler, retries=2).transcribe(WAV))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


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


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        # A negative retry count empties ``range(retries + 1)``, so the
        # request loop never runs and the placeholder failure is raised
        # without a request ever leaving the process - indistinguishable, from
        # the outside, from the deployment being down.
        ({"retries": -1}, "retries"),
        ({"backoff_seconds": -1.0}, "backoff_seconds"),
        # Both go into the multipart body; empty ones mean asking the service
        # to pick, which is not something this client knows the answer to.
        ({"model": ""}, "model"),
        ({"language": ""}, "language"),
    ],
)
def test_a_client_refuses_settings_it_could_not_act_on(
    kwargs: dict, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        EliceSttClient(
            httpx.AsyncClient(
                base_url="https://stt.invalid",
                transport=httpx.MockTransport(lambda r: httpx.Response(200)),
            ),
            **kwargs,
        )


async def test_no_retries_means_exactly_one_request() -> None:
    """The boundary the validation protects: zero is allowed and still sends."""

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(503)

    with pytest.raises(SttError):
        await client_for(handler, retries=0).transcribe(WAV)

    assert len(seen) == 1


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
