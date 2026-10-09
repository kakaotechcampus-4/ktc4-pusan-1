"""The Elice client: its wire format, its retries, and the hallucination guard.

The deployment is vLLM's OpenAI-compatible server (#159). Bodies here are
shaped like its ``verbose_json`` answers; the one captured from a real call
sits in :data:`REAL_VERBOSE_BODY`.
"""

import asyncio

import httpx
import pytest

from irya_ai.config import Settings
from irya_ai.stt import elice
from irya_ai.stt.elice import (
    MAX_RETRY_AFTER_SECONDS,
    RESPONSE_FORMAT,
    TIMESTAMP_TOLERANCE_MS,
    EliceSttClient,
    SttError,
    Transcription,
    build_client,
    build_http_client,
    is_hallucinated,
    is_stock_phrase,
    parse_response,
)

WAV = b"RIFF....WAVEfmt "

# An integer JSON can carry and a float cannot hold. Converting it - which
# ``math.isfinite`` does - raises ``OverflowError``.
HUGE = 10**400

# What the new deployment answered for a 10.5 s Korean TTS clip on 2026-10-06
# with ``response_format=verbose_json``: sentence-sized segments carrying the
# model's own quality figures, ``no_speech_prob`` null, ``words`` empty.
REAL_VERBOSE_BODY = {
    "duration": 10.495,
    "language": "ko",
    "text": " 안녕하세요. 저는 백엔드 개발자입니다. 응답 시간을 절반으로 줄였습니다.",
    "segments": [
        {
            "id": 0,
            "avg_logprob": -0.0727,
            "compression_ratio": 0.9277,
            "end": 4.78,
            "no_speech_prob": None,
            "seek": 0,
            "start": 0.0,
            "temperature": 0.0,
            "text": " 안녕하세요. 저는 백엔드 개발자입니다.",
            "tokens": [50365, 50604],
        },
        {
            "id": 1,
            "avg_logprob": -0.0451,
            "compression_ratio": 0.9195,
            "end": 9.4,
            "no_speech_prob": None,
            "seek": 0,
            "start": 5.78,
            "temperature": 0.0,
            "text": " 응답 시간을 절반으로 줄였습니다.",
            "tokens": [50654, 50835],
        },
    ],
    "words": [],
}

# What the same deployment answers without ``response_format``: text and a
# billing figure, no timing at all.
REAL_JSON_BODY = {"text": " 안녕하세요.", "usage": {"type": "duration", "seconds": 11}}

# The previous (BentoML) deployment's shape. Reading it as silence is the bug
# that emptied every caption when the deployment changed.
LEGACY_BODY = {
    "_result": {"status": "ok", "reason": None},
    "transcript": {
        "text": "안녕하세요",
        "chunks": [{"timestamp": [0.0, 1.0], "text": "안녕하세요"}],
    },
}


def body(text: str, spans: list[list[float]] | None = None) -> dict:
    return {
        "text": text,
        "segments": [
            {"id": index, "start": start, "end": end, "text": text}
            for index, (start, end) in enumerate(spans or [[0.0, 1.0]])
        ],
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


def test_parse_response_reads_a_real_verbose_json_body() -> None:
    """Extra per-segment fields are ignored; the text and the last end are read."""

    result = parse_response(REAL_VERBOSE_BODY, latency_ms=1200)

    assert result.text.startswith("안녕하세요.")
    assert result.text.endswith("줄였습니다.")
    assert result.span_end_ms == 9400
    assert not result.is_empty


def test_parse_response_reads_the_plain_json_body_without_timing() -> None:
    """The default shape has no segments, so the guard has nothing to judge."""

    result = parse_response(REAL_JSON_BODY, latency_ms=1)

    assert result.text == "안녕하세요."
    assert result.span_end_ms is None


def test_parse_response_without_segments_has_no_span() -> None:
    result = parse_response({"text": " 네 "}, latency_ms=1)

    assert result.text == "네"
    assert result.span_end_ms is None


def test_an_empty_text_is_silence() -> None:
    assert parse_response({"text": "", "segments": []}, latency_ms=0).is_empty
    assert parse_response({"text": "   "}, latency_ms=0).is_empty


def test_the_legacy_bentoml_shape_is_malformed_not_silent() -> None:
    """Regression for #159.

    The old parser read ``transcript.text`` and treated a body without it as
    an empty transcription, so when the deployment switched shapes every
    segment was dropped as ``EMPTY`` with nothing in the log to say why. A
    body with no ``text`` key is a shape this parser does not understand.
    """

    with pytest.raises(SttError) as caught:
        parse_response(LEGACY_BODY, latency_ms=0)

    assert caught.value.code == "STT_MALFORMED_RESPONSE"


def test_parse_response_raises_when_the_service_reports_failure() -> None:
    payload = {"error": {"message": "decode failed", "type": "invalid_request"}}

    with pytest.raises(SttError) as caught:
        parse_response(payload, latency_ms=0)

    assert caught.value.code == "STT_PROVIDER_ERROR"


def test_the_provider_message_never_reaches_the_error_that_gets_logged() -> None:
    """``error.message`` is free-form provider text and the error message is logged."""

    canary = "SYNTHETIC_PRIVATE_RESPONSE_MARKER"
    payload = {"error": {"message": canary}}

    with pytest.raises(SttError) as caught:
        parse_response(payload, latency_ms=0)

    assert canary not in str(caught.value)
    assert canary not in repr(caught.value.args)


def segment(**fields) -> dict:
    return {"text": "안녕", "segments": [fields]}


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="list_root"),
        pytest.param("plain text", id="string_root"),
        pytest.param({}, id="no_text_key"),
        pytest.param({"text": None}, id="null_text"),
        pytest.param({"text": 12}, id="text_is_a_number"),
        pytest.param({"text": "안녕", "segments": {}}, id="segments_is_a_mapping"),
        pytest.param(
            {"text": "안녕", "segments": [[0.0, 1.0]]}, id="segment_is_a_pair"
        ),
        pytest.param({"text": "안녕", "segments": ["0,1"]}, id="segment_is_a_string"),
        pytest.param(segment(start=0, end="x"), id="end_is_a_string"),
        pytest.param(segment(start=0, end=True), id="end_is_a_bool"),
        pytest.param(segment(start=0, end=-1.0), id="negative_end"),
        pytest.param(segment(start=0, end=1e12), id="end_past_any_interview"),
        # The start is checked too, even though only the end is used: a span
        # whose start makes no sense is not a span whose end can be trusted.
        pytest.param(segment(start=-1.0, end=2.0), id="negative_start"),
        pytest.param(segment(start="0.0", end=2.0), id="start_is_a_string"),
        pytest.param(segment(start=True, end=2.0), id="start_is_a_bool"),
        pytest.param(segment(start=1e12, end=2.0), id="start_past_any_interview"),
        pytest.param(segment(start=3.0, end=2.0), id="start_after_end"),
        pytest.param(segment(start=float("nan"), end=2.0), id="start_is_not_a_number"),
        # JSON integers have no upper bound, and Python parses them at full
        # precision. Anything that converts one of these to a float - which
        # includes ``math.isfinite`` - raises ``OverflowError``, so the
        # magnitude has to be refused before any conversion touches it.
        pytest.param(segment(start=0, end=HUGE), id="end_is_too_large_for_a_float"),
        pytest.param(segment(start=HUGE, end=1), id="start_is_too_large_for_a_float"),
        pytest.param(segment(start=0, end=-HUGE), id="end_is_too_negative_for_a_float"),
        pytest.param(
            segment(start=-HUGE, end=1), id="start_is_too_negative_for_a_float"
        ),
    ],
)
def test_a_malformed_body_becomes_a_typed_error_not_a_type_error(payload) -> None:
    """The boundary owns every shape, so nothing else has to guess at one.

    Each of these would otherwise escape as ``AttributeError``, ``KeyError``
    or ``TypeError`` into a caller iterating a live stream, which kills the
    iteration outright.
    """

    with pytest.raises(SttError) as caught:
        parse_response(payload, latency_ms=0)

    assert caught.value.code == "STT_MALFORMED_RESPONSE"
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    ("payload", "text", "span_end_ms"),
    [
        pytest.param({"text": "네", "segments": None}, "네", None, id="null_segments"),
        pytest.param({"text": "네", "segments": []}, "네", None, id="no_segments"),
        pytest.param(
            {"text": "네", "segments": [{"text": "네"}]},
            "네",
            None,
            id="segment_without_timing",
        ),
        pytest.param(
            segment(start=0.0, end=None), "안녕", None, id="unclosed_trailing_segment"
        ),
        pytest.param(segment(start=0, end=2), "안녕", 2000, id="integer_timestamps"),
        # A null start is allowed for the same reason a null end is: this
        # parser reads the end, and says so rather than requiring a start it
        # has no use for.
        pytest.param(
            segment(start=None, end=2.0), "안녕", 2000, id="segment_without_a_start"
        ),
        pytest.param(
            segment(start=2.0, end=2.0), "안녕", 2000, id="an_instant_is_a_span"
        ),
        pytest.param({"text": "네", "error": None}, "네", None, id="null_error"),
    ],
)
def test_an_absent_field_is_an_answer_and_not_a_malformed_body(
    payload, text, span_end_ms
) -> None:
    """A field the service omits is a shape this parser understands.

    Absent timings mean the hallucination guard has nothing to judge. That is
    not a provider failure, and conflating it with one would turn a normal
    segment into an error.
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
        return httpx.Response(200, json=segment(start=0, end=HUGE))

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


async def test_a_closed_client_is_a_final_typed_error() -> None:
    """``httpx`` says it with a bare ``RuntimeError``; callers catch ``SttError``."""

    seen: list[httpx.Request] = []
    client = client_for(lambda request: seen.append(request), retries=2)
    await client.client.aclose()

    with pytest.raises(SttError) as caught:
        await client.transcribe(WAV)

    assert caught.value.code == "STT_CLIENT_CLOSED"
    assert caught.value.retryable is False
    assert caught.value.__cause__ is None
    assert seen == []


def recorded_sleeps(monkeypatch) -> list[float]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(elice.asyncio, "sleep", fake_sleep)
    return slept


@pytest.mark.parametrize(
    "retry_after",
    ["7", "Wed, 21 Oct 2099 07:28:00 GMT"],
    ids=["seconds", "http_date"],
)
async def test_a_retry_waits_at_least_what_retry_after_asked(
    monkeypatch, retry_after: str
) -> None:
    """Retrying sooner than asked only adds to the load being shed."""

    slept = recorded_sleeps(monkeypatch)
    monkeypatch.setattr(elice, "MAX_RETRY_AFTER_SECONDS", float("inf"))
    answers = iter(
        [
            httpx.Response(429, headers={"Retry-After": retry_after}),
            httpx.Response(200, json=body("다시 받았습니다")),
        ]
    )

    result = await client_for(lambda request: next(answers), retries=2).transcribe(WAV)

    assert result.text == "다시 받았습니다"
    assert len(slept) == 1 and slept[0] >= 7.0


async def test_a_retry_after_longer_than_a_caption_lasts_fails_now(
    monkeypatch,
) -> None:
    slept = recorded_sleeps(monkeypatch)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        wait = str(int(MAX_RETRY_AFTER_SECONDS) + 1)
        return httpx.Response(503, headers={"Retry-After": wait})

    with pytest.raises(SttError) as caught:
        await client_for(handler, retries=2).transcribe(WAV)

    assert caught.value.code == "STT_REQUEST_FAILED"
    assert len(seen) == 1
    assert slept == []


@pytest.mark.parametrize(
    "retry_after", [b"soon", b"-3", "\u0661\u0662".encode(), b"Wed, 21 Oct 1999"]
)
async def test_a_retry_after_that_is_not_a_wait_is_ignored(
    monkeypatch, retry_after: bytes
) -> None:
    slept = recorded_sleeps(monkeypatch)
    answers = iter(
        [
            httpx.Response(429, headers=[(b"Retry-After", retry_after)]),
            httpx.Response(200, json=body("다시 받았습니다")),
        ]
    )

    result = await client_for(lambda request: next(answers), retries=1).transcribe(WAV)

    assert result.text == "다시 받았습니다"
    assert slept == [0.0]


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


@pytest.mark.parametrize(
    "text",
    [
        "시청해주셔서 감사합니다",
        "시청해 주셔서 감사합니다.",
        " 구독과 좋아요 부탁드립니다! ",
        "시청해 주셔서 감사합니다. 구독과 좋아요 부탁드립니다.",
        "MBC 뉴스 김지경입니다.",
        "자막 제공 및 자막 편집",
    ],
)
def test_a_stock_outro_is_recognised_however_it_is_spaced(text: str) -> None:
    """The span can fit the audio; the text alone gives it away."""

    assert is_stock_phrase(text)


@pytest.mark.parametrize(
    "text",
    [
        "감사합니다",
        "네 감사합니다",
        "끝까지 들어 주셔서 감사합니다",
        "유튜브에서 시청해 주셔서 감사합니다라는 말로 마무리했습니다",
        "구독과 좋아요 기능을 직접 구현했습니다",
        "MBC 뉴스 인턴으로 일했습니다",
        "",
        "...",
    ],
)
def test_speech_that_shares_words_with_an_outro_is_kept(text: str) -> None:
    """Only the whole credit is stock; a candidate's own sentence never is."""

    assert not is_stock_phrase(text)


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
    assert 'name="model"' in payload and "whisper-large-v3" in payload
    # ISO 639-1, as the OpenAI transcription API defines it.
    assert 'name="language"' in payload and "\r\n\r\nko\r\n" in payload
    # Without this the body is text alone and the hallucination guard is blind.
    assert RESPONSE_FORMAT == "verbose_json"
    assert 'name="response_format"' in payload and "verbose_json" in payload


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
        elice_stt_language="ko",
    )

    client = build_client(
        settings, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )

    assert client.model == "whisper-large-v3"
    assert client.language == "ko"
    assert str(client.client.base_url) == "https://stt.invalid"
    assert client.client.headers["authorization"] == "Bearer unit-test-token"
