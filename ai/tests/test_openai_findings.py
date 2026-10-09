"""HTTP stubs for the gateway contract; no real model or network."""

import json

import httpx
import pytest
from openai import AsyncOpenAI

from irya_ai.findings import FindingsAgent, FindingsError
from irya_ai.openai_findings import (
    SYSTEM_PROMPT,
    OpenAIFindingsGenerator,
    build_payload,
)
from irya_ai.schemas.findings import FindingsDraft
from irya_ai.schemas.transcript import TranscriptSnapshot
from test_findings import context, draft, utterance


def client_for(handler):
    return AsyncOpenAI(
        api_key="test-key",
        base_url="https://gateway.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def response(items=None, **changes):
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
                    "content": json.dumps(
                        {
                            "findings": [draft().model_dump(mode="json")]
                            if items is None
                            else items
                        }
                    ),
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    body.update(changes)
    return body


def test_payload_does_not_send_names_body_storage_or_timestamps():
    payload = build_payload(context(), [utterance()])
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "이름을 모델에 보내지 않음" not in dumped
    assert "본문을 모델에 보내지 않음" not in dumped
    assert "private-storage-key" not in dumped
    assert "startMs" not in dumped
    assert payload["resumeClaims"][0]["claimId"] == "clm_test"
    schema = FindingsDraft.model_json_schema()
    assert set(schema["$defs"]["FindingDraft"]["required"]) == {
        "type",
        "competency_id",
        "claim_id",
        "evidence_utterance_id",
        "evidence_quote",
        "summary",
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
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json=response())

    async with client_for(handler) as client:
        generator = OpenAIFindingsGenerator(client, reasoning_effort="low")
        result = await FindingsAgent(generator).run(
            context(),
            TranscriptSnapshot(session_id="ses_test", utterances=[utterance()]),
        )
    assert result.status == "completed"
    assert result.model == "served-model@findings-v2"
    assert result.usage.prompt_tokens == 100
    assert result.findings[0].evidence_t_ms == 1000


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
        lambda request: httpx.Response(
            status, json={"error": {"message": "private-response"}}
        )
    ) as client:
        with pytest.raises(FindingsError) as got:
            await OpenAIFindingsGenerator(client).generate(context(), [utterance()])
    assert got.value.code == code
    assert got.value.retryable is retryable
    assert "private-response" not in str(got.value)


@pytest.mark.parametrize(
    "body",
    [
        response(choices=[]),
        response(items=[{"summary": "private-body"}]),
        {},
        response(
            choices=[
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "refusal": "private-refusal",
                    },
                }
            ]
        ),
        response(
            choices=[
                {
                    "index": 0,
                    "finish_reason": "length",
                    "message": {"role": "assistant", "content": "{"},
                }
            ]
        ),
    ],
)
async def test_malformed_or_refused_output_returns_failure(body):
    async with client_for(lambda request: httpx.Response(200, json=body)) as client:
        result = await FindingsAgent(OpenAIFindingsGenerator(client)).run(
            context(),
            TranscriptSnapshot(session_id="ses_test", utterances=[utterance()]),
        )
    assert result.status == "failed"
    assert result.findings == []
    assert "private" not in result.model_dump_json()


def test_prompt_asks_for_no_more_than_the_code_keeps():
    # The gateway caps output at 2,000 tokens; asking for more findings or
    # longer summaries than the code accepts only spends them on rejects.
    assert "최대 8개" in SYSTEM_PROMPT
    assert "120자 이내" in SYSTEM_PROMPT
