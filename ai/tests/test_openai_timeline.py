"""The OpenAI-compatible timeline generator against a stubbed HTTP transport.

No network and no key. The transport asserts the request shape the Elice
gateway requires (chat completions, no unsupported parameters) and returns
canned completions to exercise parsing and error mapping.
"""

import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import TypeAdapter

from irya_ai.openai_timeline import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    OpenAITimelineGenerator,
    build_payload,
)
from irya_ai.pipeline.qa_segmentation import segment_qa
from irya_ai.schemas import QAPair, TranscriptSnapshot, Utterance
from irya_ai.timeline import (
    ReviewTimelineAgent,
    TimelineError,
    select_qa_pairs,
    snapshot_from_chunks,
)

CHUNKS = (
    Path(__file__).resolve().parents[1] / "data/samples/chunks_backend_junior_01.json"
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
def snapshot() -> TranscriptSnapshot:
    chunks = TypeAdapter(list[Utterance]).validate_json(CHUNKS.read_text("utf-8"))
    return snapshot_from_chunks(chunks)


@pytest.fixture
def selected(snapshot: TranscriptSnapshot) -> list[QAPair]:
    return select_qa_pairs(segment_qa(snapshot.final_utterances()).qa_pairs)


def sources_of(snapshot: TranscriptSnapshot) -> dict[str, Utterance]:
    return {u.utterance_id: u for u in snapshot.final_utterances()}


def completion_body(
    moments: list[dict],
    *,
    finish_reason: str = "stop",
    refusal: str | None = None,
    content: str | None = None,
) -> dict:
    text = content if content is not None else json.dumps({"moments": moments})
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
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "prompt_tokens_details": {"cached_tokens": 900},
        },
    }


def client_for(handler) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="test-only-key",
        base_url="https://gateway.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def good_moment(pair: QAPair, sources: dict[str, Utterance]) -> dict:
    uid = pair.answer_utterance_ids[0]
    return {
        "qa_id": pair.qa_id,
        "label": "주제",
        "answer": "지원자가 설명했다.",
        "citations": [{"utterance_id": uid, "quote": sources[uid].content[:8]}],
    }


# --- payload -----------------------------------------------------------------


def test_payload_is_question_scoped_and_minimal(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    payload = build_payload(selected, sources_of(snapshot))

    assert list(payload) == ["qaPairs"]
    entry = payload["qaPairs"][0]
    assert set(entry) == {"qaId", "question", "answer"}
    assert set(entry["answer"][0]) == {"utteranceId", "text"}
    text = json.dumps(payload, ensure_ascii=False)
    for leaked in ("startMs", "speaker", "trackId", "seq", "passType", "words"):
        assert leaked not in text


def test_prompt_pins_the_contract() -> None:
    assert PROMPT_VERSION == "timeline-v1"
    assert "12자" in SYSTEM_PROMPT
    assert "quote" in SYSTEM_PROMPT and "utteranceId" in SYSTEM_PROMPT


# --- request shape -------------------------------------------------------------


async def test_request_uses_chat_completions_with_only_supported_params(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    requests: list[httpx.Request] = []
    sources = sources_of(snapshot)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json=completion_body([good_moment(p, sources) for p in selected])
        )

    async with client_for(handler) as client:
        generator = OpenAITimelineGenerator(client, reasoning_effort="low")
        draft = await generator.generate(selected, sources)

    request = requests[0]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-only-key"
    body = json.loads(request.content)
    assert set(body) <= SUPPORTED_CHAT_PARAMS, set(body) - SUPPORTED_CHAT_PARAMS
    assert "store" not in body
    assert body["model"] == "gpt-5.6-luna"
    assert body["reasoning_effort"] == "low"
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert len(draft.moments) == len(selected)
    assert generator.last_model == "gpt-5.6-luna-2026-02"
    assert generator.last_usage is not None
    assert generator.last_usage.cached_prompt_tokens == 900


async def test_reasoning_effort_is_omitted_unless_configured(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion_body([]))

    async with client_for(handler) as client:
        await OpenAITimelineGenerator(client, model="gpt-5.6-terra").generate(
            selected, sources_of(snapshot)
        )

    assert "reasoning_effort" not in bodies[0]
    assert bodies[0]["model"] == "gpt-5.6-terra"


async def test_no_request_for_empty_selection(snapshot: TranscriptSnapshot) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call the model")

    async with client_for(handler) as client:
        draft = await OpenAITimelineGenerator(client).generate([], sources_of(snapshot))

    assert draft.moments == []


# --- end to end through the agent -----------------------------------------------


async def test_agent_verifies_model_output_and_reports_usage(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    sources = sources_of(snapshot)
    moments = [good_moment(p, sources) for p in selected]
    moments[1]["citations"][0]["quote"] = "원문에 없는 문장"  # rejected
    moments[2]["answer"] = "응답 시간을 99% 줄였다"  # number not in evidence

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion_body(moments))

    async with client_for(handler) as client:
        result = await ReviewTimelineAgent(
            OpenAITimelineGenerator(client), model="gpt-5.6-luna"
        ).run(snapshot)

    assert result.status == "partial"
    assert result.rejected_moment_count == 2
    assert len(result.moments) == len(selected) - 2
    assert result.model == "gpt-5.6-luna-2026-02"  # what the gateway served
    assert result.usage is not None and result.usage.prompt_tokens == 1200
    assert "원문에 없는 문장" not in result.model_dump_json()


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
            httpx.Response(200, json=completion_body([], refusal="거부")),
            "LLM_REFUSED",
            False,
        ),
        (
            httpx.Response(200, json=completion_body([], finish_reason="length")),
            "LLM_INCOMPLETE_OUTPUT",
            False,
        ),
        (
            httpx.Response(200, json=completion_body([], content="not json")),
            "LLM_INVALID_OUTPUT",
            False,
        ),
    ],
)
async def test_provider_failures_become_safe_codes(
    snapshot: TranscriptSnapshot,
    selected: list[QAPair],
    response: httpx.Response,
    code: str,
    retryable: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    async with client_for(handler) as client:
        with pytest.raises(TimelineError) as info:
            await OpenAITimelineGenerator(client).generate(
                selected, sources_of(snapshot)
            )

    assert info.value.code == code
    assert info.value.retryable is retryable
    assert "bad key" not in str(info.value)


async def test_connection_error_is_retryable(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with client_for(handler) as client:
        with pytest.raises(TimelineError) as info:
            await OpenAITimelineGenerator(client).generate(
                selected, sources_of(snapshot)
            )

    assert info.value.code == "LLM_UNAVAILABLE" and info.value.retryable


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"choices": None},
        {"choices": [None]},
        {"choices": [{"index": 0, "finish_reason": "stop", "message": None}]},
        {**completion_body([]), "usage": {"prompt_tokens": "private-response"}},
    ],
)
async def test_malformed_success_response_returns_safe_failure(
    snapshot: TranscriptSnapshot, body: object
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps(body))

    async with client_for(handler) as client:
        result = await ReviewTimelineAgent(OpenAITimelineGenerator(client)).run(
            snapshot
        )

    assert result.status == "failed"
    assert result.error.code == "LLM_INVALID_OUTPUT"
    assert result.error.retryable is False
    assert result.moments == []
    assert result.qa_pairs
    assert "private-response" not in result.model_dump_json()
