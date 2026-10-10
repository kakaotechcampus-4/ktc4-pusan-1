"""The OpenAI-compatible prep generator against a stubbed HTTP transport.

No network and no key. The transport asserts the request shape the Elice
gateway requires (chat completions, no unsupported parameters) and returns
canned completions to exercise parsing and error mapping.
"""

import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI

from irya_ai.openai_prep import (
    INPUT_MAX_CHARS,
    MAX_COMPLETION_TOKENS,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    OpenAIPrepGenerator,
    build_payload,
)
from irya_ai.prep import PrepAgent, PrepError
from irya_ai.schemas import InterviewContext

CONTEXT = (
    Path(__file__).resolve().parents[1] / "data/samples/context_backend_junior.json"
)
SUPPORTED_CHAT_PARAMS = {
    "model",
    "messages",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "stop",
    "stream",
    "tools",
    "tool_choice",
    "response_format",
    "reasoning_effort",
}


@pytest.fixture
def context() -> InterviewContext:
    return InterviewContext.model_validate_json(CONTEXT.read_text("utf-8"))


def completion_body(
    draft: dict | None,
    *,
    finish_reason: str = "stop",
    refusal: str | None = None,
    content: str | None = None,
) -> dict:
    text = content if content is not None else json.dumps(draft, ensure_ascii=False)
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-5.6-luna-2026-02",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": None if refusal else text,
                    "refusal": refusal,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 1500,
            "completion_tokens": 400,
            "prompt_tokens_details": {"cached_tokens": 1100},
        },
    }


def client_for(handler) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="test-only-key",
        base_url="https://gateway.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def good_draft(context: InterviewContext) -> dict:
    first_claim = context.resume_claims[0].quote
    return {
        "competencies": [
            {
                "name": "대용량 트래픽",
                "required": True,
                "description": "병목 개선 경험",
            },
            {"name": "협업", "required": True, "description": "역할 조율 경험"},
            {"name": "장애 대응", "required": False, "description": "원인 분석 경험"},
        ],
        "resume_claims": [
            {"quote": first_claim, "section": "프로젝트"},
            {"quote": "Kubernetes 기반 배포 파이프라인 구축", "section": None},
        ],
    }


# --- payload -----------------------------------------------------------------


def test_payload_is_static_first_and_carries_no_candidate_name(
    context: InterviewContext,
) -> None:
    payload, truncated = build_payload(context)

    assert list(payload) == ["job", "company", "limits", "resume"]
    assert set(payload["job"]) == {"title", "description"}
    assert payload["company"]["name"] == context.company.name
    assert payload["company"]["culture"] == context.company.culture
    assert payload["limits"] == {"maxCompetencies": 6, "maxClaims": 12}
    assert payload["resume"] == {"text": context.resume.text.strip()}
    assert truncated is False
    text = json.dumps(payload, ensure_ascii=False)
    assert context.candidate.name not in text
    for leaked in ("candidateId", "resumeId", "storageKey", "sessionId", "rubric"):
        assert leaked not in text


def test_payload_omits_the_resume_when_there_is_no_body(
    context: InterviewContext,
) -> None:
    without = context.model_copy(
        update={"resume": context.resume.model_copy(update={"text": None})}
    )
    payload, _ = build_payload(without)
    assert "resume" not in payload

    blank = context.model_copy(
        update={"resume": context.resume.model_copy(update={"text": "  \n"})}
    )
    payload, _ = build_payload(blank)
    assert "resume" not in payload


def test_payload_cuts_long_bodies_and_says_so(context: InterviewContext) -> None:
    long_resume = context.resume.model_copy(update={"text": "경력 사항입니다. " * 2000})
    payload, truncated = build_payload(
        context.model_copy(update={"resume": long_resume})
    )

    assert truncated is True
    assert len(payload["resume"]["text"]) == INPUT_MAX_CHARS

    payload, truncated = build_payload(context, max_input_chars=20)
    assert truncated is True
    assert len(payload["job"]["description"]) == 20


def test_prompt_pins_the_contract() -> None:
    assert PROMPT_VERSION == "prep-v1"
    assert "20자" in SYSTEM_PROMPT and "120자" in SYSTEM_PROMPT
    assert "10자 이상 200자 이내" in SYSTEM_PROMPT
    assert "quote" in SYSTEM_PROMPT and "section" in SYSTEM_PROMPT
    assert "평가" in SYSTEM_PROMPT


# --- request shape -------------------------------------------------------------


async def test_request_uses_chat_completions_with_only_supported_params(
    context: InterviewContext,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=completion_body(good_draft(context)))

    async with client_for(handler) as client:
        generator = OpenAIPrepGenerator(client, reasoning_effort="low")
        draft = await generator.generate(context)

    request = requests[0]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-only-key"
    body = json.loads(request.content)
    assert set(body) <= SUPPORTED_CHAT_PARAMS, set(body) - SUPPORTED_CHAT_PARAMS
    assert "store" not in body
    assert body["model"] == "gpt-5.6-luna"
    assert body["reasoning_effort"] == "low"
    # The gateway rejects a larger non-streaming budget with 400.
    assert body["max_completion_tokens"] == MAX_COMPLETION_TOKENS <= 2000
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert len(draft.competencies) == 3
    assert len(draft.resume_claims) == 2
    assert generator.last_model == "gpt-5.6-luna-2026-02"
    assert generator.last_usage is not None
    assert generator.last_usage.cached_prompt_tokens == 1100
    assert generator.last_truncated is False


async def test_reasoning_effort_is_omitted_unless_configured(
    context: InterviewContext,
) -> None:
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion_body(good_draft(context)))

    async with client_for(handler) as client:
        await OpenAIPrepGenerator(client, model="gpt-5.6-terra").generate(context)

    assert "reasoning_effort" not in bodies[0]
    assert bodies[0]["model"] == "gpt-5.6-terra"


async def test_the_structured_output_schema_requires_every_draft_key(
    context: InterviewContext,
) -> None:
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion_body(good_draft(context)))

    async with client_for(handler) as client:
        await OpenAIPrepGenerator(client).generate(context)

    schema = bodies[0]["response_format"]["json_schema"]
    assert schema["strict"] is True
    claim = schema["schema"]["$defs"]["ResumeClaimDraft"]
    assert set(claim["required"]) == {"quote", "section"}


# --- end to end through the agent -----------------------------------------------


async def test_agent_verifies_model_output_and_reports_usage(
    context: InterviewContext,
) -> None:
    draft = good_draft(context)
    draft["resume_claims"].append(
        {"quote": "이력서에 없는 문장을 지어냈습니다.", "section": None}
    )
    draft["competencies"].append(
        {"name": "가" * 30, "required": True, "description": "이름이 너무 깁니다"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion_body(draft))

    async with client_for(handler) as client:
        result = await PrepAgent(OpenAIPrepGenerator(client), model="gpt-5.6-luna").run(
            context
        )

    assert result.status == "partial"
    assert len(result.competencies) == 3
    assert len(result.resume_claims) == 2
    assert result.rejections == [
        "competency 4: name longer than 20 chars",
        "claim 3: quote not found in resume",
    ]
    assert result.model == "gpt-5.6-luna-2026-02"  # what the gateway served
    assert result.usage is not None and result.usage.prompt_tokens == 1500
    assert "지어냈습니다" not in result.model_dump_json()


async def test_a_truncated_input_is_reported_as_a_warning(
    context: InterviewContext,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion_body(good_draft(context)))

    async with client_for(handler) as client:
        generator = OpenAIPrepGenerator(client, max_input_chars=50)
        result = await PrepAgent(generator).run(context)

    assert generator.last_truncated is True
    assert "INPUT_TRUNCATED" in result.warnings
    # Verification still runs against the whole resume, not the cut.
    assert result.status == "completed"


# --- error mapping ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "code", "retryable"),
    [
        (
            httpx.Response(401, json={"error": {"message": "bad key"}}),
            "LLM_AUTH_FAILED",
            False,
        ),
        (
            httpx.Response(
                400, json={"error": {"message": "unsupported parameter: store"}}
            ),
            "LLM_BAD_REQUEST",
            False,
        ),
        (
            httpx.Response(429, json={"error": {"message": "slow down"}}),
            "LLM_RATE_LIMITED",
            True,
        ),
        (
            httpx.Response(503, json={"error": {"message": "down"}}),
            "LLM_API_ERROR",
            True,
        ),
        (
            httpx.Response(200, json=completion_body(None, refusal="거부")),
            "LLM_REFUSED",
            False,
        ),
        (
            httpx.Response(200, json=completion_body(None, finish_reason="length")),
            "LLM_INCOMPLETE_OUTPUT",
            False,
        ),
        (
            httpx.Response(200, json=completion_body(None, content="not json")),
            "LLM_INVALID_OUTPUT",
            False,
        ),
    ],
)
async def test_provider_failures_become_safe_codes(
    context: InterviewContext,
    response: httpx.Response,
    code: str,
    retryable: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    async with client_for(handler) as client:
        with pytest.raises(PrepError) as info:
            await OpenAIPrepGenerator(client).generate(context)

    assert info.value.code == code
    assert info.value.retryable is retryable
    assert "bad key" not in str(info.value)


async def test_connection_error_is_retryable(context: InterviewContext) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with client_for(handler) as client:
        with pytest.raises(PrepError) as info:
            await OpenAIPrepGenerator(client).generate(context)

    assert info.value.code == "LLM_UNAVAILABLE" and info.value.retryable
