import json

import httpx
import pytest
from openai import AsyncOpenAI

from irya_ai.analysis import ContextAnalysisAgent
from irya_ai.openai_summary import OpenAISummarizer
from irya_ai.transcript import Transcript


def response_body(points: list[dict], *, status: str = "completed") -> dict:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "model": "gpt-4o-mini-2024-07-18",
        "status": status,
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"points": points}, ensure_ascii=False),
                        "annotations": [],
                    }
                ],
            }
        ],
    }


def client_for(handler) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="test-only-key",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


GOOD = {
    "text": "응답 시간을 40% 줄였다고 설명했다.",
    "citations": [{"utterance_id": "u-004", "quote": "응답 시간을 40% 줄였고"}],
}


async def test_real_sdk_request_and_parsing_with_stubbed_http(
    sample_transcript: Transcript,
) -> None:
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response_body([GOOD]))

    async with client_for(handler) as client:
        result = await ContextAnalysisAgent(OpenAISummarizer(client)).analyze(
            sample_transcript
        )

    assert result.status == "completed"
    request = requests[0]
    assert request.url.path == "/v1/responses"
    body = json.loads(request.content)
    assert body["model"] == "gpt-4o-mini"
    assert body["store"] is False
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    sent = json.loads(body["input"][1]["content"])
    assert len(sent["utterances"]) == 4
    assert "u-004-partial" not in body["input"][1]["content"]
    assert result.summary_result.source_utterance_ids == ["u-004"]
    assert result.summary_result.model == "gpt-4o-mini-2024-07-18"


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, "LLM_API_ERROR", False),
        (429, "LLM_RATE_LIMITED", True),
        (503, "LLM_API_ERROR", True),
    ],
)
async def test_http_errors_are_safe_and_preserve_qa(
    sample_transcript: Transcript, status_code: int, expected_code: str, retryable: bool
) -> None:
    def handler(request):
        return httpx.Response(
            status_code,
            json={"error": {"message": "private-provider-body", "type": "api_error"}},
        )

    async with client_for(handler) as client:
        result = await ContextAnalysisAgent(OpenAISummarizer(client)).analyze(
            sample_transcript
        )
    assert result.status == "failed"
    assert result.error.code == expected_code
    assert result.error.retryable is retryable
    assert len(result.qa_pairs) == 2
    assert "private-provider-body" not in result.model_dump_json()


async def test_partial_grounding_and_model_override(
    sample_transcript: Transcript,
) -> None:
    def handler(request):
        assert json.loads(request.content)["model"] == "gpt-4o"
        bad = {"text": "허구", "citations": [{"utterance_id": "bad", "quote": "허구"}]}
        return httpx.Response(200, json=response_body([GOOD, bad]))

    async with client_for(handler) as client:
        result = await ContextAnalysisAgent(
            OpenAISummarizer(client, model="gpt-4o")
        ).analyze(sample_transcript)
    assert result.status == "partial"
    assert result.summary_result.rejected_point_count == 1
    assert "허구" not in result.summary_result.summary


@pytest.mark.parametrize("kind", ["refusal", "invalid_json", "incomplete", "no_points"])
async def test_unusable_responses_fail_without_fabricated_summary(
    sample_transcript: Transcript, kind: str
) -> None:
    def handler(request):
        body = response_body([] if kind == "no_points" else [GOOD])
        if kind == "refusal":
            body["output"][0]["content"] = [{"type": "refusal", "refusal": "refused"}]
        elif kind == "invalid_json":
            body["output"][0]["content"][0]["text"] = "not-json"
        elif kind == "incomplete":
            body["status"] = "incomplete"
            body["incomplete_details"] = {"reason": "max_output_tokens"}
        return httpx.Response(200, json=body)

    async with client_for(handler) as client:
        result = await ContextAnalysisAgent(OpenAISummarizer(client)).analyze(
            sample_transcript
        )
    assert result.status == "failed"
    assert result.summary_result is None
    assert len(result.qa_pairs) == 2
