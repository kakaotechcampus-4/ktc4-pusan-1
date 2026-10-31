"""HTTP stubs for the gateway contract; no real model or network."""

import json

import httpx
import pytest
from openai import AsyncOpenAI

from irya_ai.openai_report import (
    SYSTEM_PROMPT,
    OpenAIReportGenerator,
    build_payload,
)
from irya_ai.report import ReportAgent, ReportError
from irya_ai.schemas.report import ReportDraft
from test_report import block, context, draft


def client_for(handler):
    return AsyncOpenAI(
        api_key="test-key",
        base_url="https://gateway.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def response(content: ReportDraft | None = None, **changes):
    body = {
        "id": "stub",
        "object": "chat.completion",
        "created": 0,
        "model": "served-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": (content or draft()).model_dump_json(),
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    body.update(changes)
    return body


def test_payload_sends_ids_text_and_summary_but_no_memo_or_timestamps():
    ctx = context()
    payload = build_payload(ctx, ctx.competencies[:1])
    dumped = json.dumps(payload, ensure_ascii=False)
    assert payload["summary"]["overview"] == "캐시와 결제를 이야기한 면접."
    assert [c["competencyId"] for c in payload["competencies"]] == ["cmp_api"]
    # The group's findings plus the one without a competency; the other
    # group's findings do not come along.
    assert [f["findingId"] for f in payload["findings"]] == [
        "fnd_cache",
        "fnd_idem",
        "fnd_free",
    ]
    assert payload["findings"][1]["quote"] == "결제 멱등키 중복 방지를 설계·구현"
    assert "atSec" not in dumped and "memo" not in dumped
    assert "점수" in SYSTEM_PROMPT and "finding_id" in SYSTEM_PROMPT
    schema = ReportDraft.model_json_schema()
    assert set(schema["$defs"]["SentenceDraft"]["required"]) == {"text", "finding_id"}
    assert set(schema["$defs"]["CompetencyReportDraft"]["required"]) == {
        "competency_id",
        "confirmed",
        "unconfirmed",
        "next_questions",
    }


async def test_supported_parameters_and_grounded_output():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert set(body) == {
            "model",
            "messages",
            "response_format",
            "max_completion_tokens",
            "reasoning_effort",
            "stream",
        }
        assert body["stream"] is False
        assert body["reasoning_effort"] == "low"
        assert body["max_completion_tokens"] <= 2000
        assert "store" not in body
        user = body["messages"][1]["content"]
        assert user == json.dumps(
            json.loads(user), ensure_ascii=False, separators=(",", ":")
        )
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json=response())

    async with client_for(handler) as client:
        generator = OpenAIReportGenerator(client)
        result = await ReportAgent(generator).run(context())
    assert result.status == "completed"
    assert result.model == "served-model@report-v1"
    assert result.usage.prompt_tokens == 100
    assert result.sentence_count == 2


async def test_competencies_are_split_across_calls_and_usage_is_summed():
    seen: list[list[str]] = []

    def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        ids = [c["competencyId"] for c in payload["competencies"]]
        seen.append(ids)
        if ids == ["cmp_api"]:
            content = draft()
        else:
            content = draft(
                block(competency_id="cmp_db", confirmed=[], unconfirmed=[]),
                overview="두 번째 호출의 overview는 버려진다",
            )
        return httpx.Response(200, json=response(content))

    async with client_for(handler) as client:
        generator = OpenAIReportGenerator(client, competencies_per_call=1)
        result = await ReportAgent(generator).run(context())
    assert seen == [["cmp_api"], ["cmp_db"]]
    assert result.status == "completed"
    assert result.overview == "전체 요약 세 줄."
    assert [c.competency_id for c in result.competencies] == ["cmp_api", "cmp_db"]
    assert result.usage.prompt_tokens == 200
    assert result.usage.completion_tokens == 100


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (400, "LLM_BAD_REQUEST", False),
        (401, "LLM_AUTH_FAILED", False),
        (429, "LLM_RATE_LIMITED", True),
        (500, "LLM_API_ERROR", True),
    ],
)
async def test_provider_errors_are_safe(status, code, retryable):
    async with client_for(
        lambda request: httpx.Response(status, json={"error": {"message": "secret"}})
    ) as client:
        generator = OpenAIReportGenerator(client)
        with pytest.raises(ReportError) as info:
            await generator.generate(context())
    assert info.value.code == code
    assert info.value.retryable is retryable
    assert "secret" not in str(info.value)


async def test_a_cut_answer_is_incomplete_and_still_counted():
    async with client_for(
        lambda request: httpx.Response(
            200,
            json=response(
                choices=[
                    {
                        "index": 0,
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": "{"},
                    }
                ]
            ),
        )
    ) as client:
        generator = OpenAIReportGenerator(client)
        result = await ReportAgent(generator).run(context())
    assert result.status == "failed"
    assert result.error.code == "LLM_INCOMPLETE_OUTPUT"
    assert result.usage.completion_tokens == 50


async def test_malformed_envelope_is_invalid_output():
    async with client_for(
        lambda request: httpx.Response(200, json={"choices": "nope"})
    ) as client:
        generator = OpenAIReportGenerator(client)
        with pytest.raises(ReportError) as info:
            await generator.generate(context())
    assert info.value.code == "LLM_INVALID_OUTPUT"


def test_rejects_zero_competencies_per_call():
    with pytest.raises(ValueError):
        OpenAIReportGenerator(
            AsyncOpenAI(api_key="k", base_url="https://gateway.test/v1"),
            competencies_per_call=0,
        )
