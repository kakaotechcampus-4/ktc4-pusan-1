"""The suggestion loop: the sink never waits, the task ingests all, posts go out."""

import asyncio
import json
import time
from datetime import UTC, datetime

import httpx
import pytest

from irya_ai.backend import BackendClient, BackendError
from irya_ai.schemas import (
    CitationDraft,
    SpeakerRole,
    SuggestionBatchDraft,
    SuggestionDraft,
    SuggestionPayload,
    Utterance,
)
from irya_ai.suggestion_runner import SuggestionRunner
from irya_ai.suggestions import FakeSuggestionGenerator, LiveSuggestionAgent

AT = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
ANSWER = "결제 API를 맡아서 초당 300건까지 처리되도록 캐시를 넣었습니다."


def utterance(**overrides) -> Utterance:
    fields = {
        "utterance_id": "utt_a",
        "session_id": "ses_123",
        "track_id": "trk_candidate",
        "speaker": SpeakerRole.CANDIDATE,
        "seq": 1,
        "start_ms": 1_000,
        "end_ms": 9_000,
        "content": ANSWER,
    }
    return Utterance(**{**fields, **overrides})


def question() -> Utterance:
    return utterance(
        utterance_id="utt_q",
        speaker=SpeakerRole.INTERVIEWER,
        track_id="trk_interviewer",
        seq=0,
        start_ms=0,
        end_ms=900,
        content="어떤 일을 하셨는지 말씀해주세요.",
    )


def more_words(n: int, *, utterance_id: str, seq: int) -> Utterance:
    return utterance(
        utterance_id=utterance_id,
        seq=seq,
        start_ms=seq * 10_000,
        end_ms=seq * 10_000 + 5_000,
        content=" ".join(f"그리고{i}" for i in range(n)),
    )


def draft(content: str = "캐시를 어디에 두셨는지 더 여쭤보세요.") -> SuggestionDraft:
    return SuggestionDraft(
        content=content,
        reason="지원자가 캐시를 언급했습니다.",
        evidence=[CitationDraft(utterance_id="utt_a", quote="캐시를 넣었습니다")],
    )


class Gated(FakeSuggestionGenerator):
    """Answers with a different draft per round, each only once released."""

    def __init__(self, *contents: str) -> None:
        super().__init__(SuggestionBatchDraft(suggestions=[]))
        self.drafts = [SuggestionBatchDraft(suggestions=[draft(c)]) for c in contents]
        self.gate = asyncio.Event()
        self.gate.set()
        self.pairs = []

    async def generate(self, pair, sources, context=None, history=None):
        self.calls.append(pair.qa_id)
        self.pairs.append(pair)
        await self.gate.wait()
        return self.drafts[len(self.calls) - 1]


class Posts:
    """Records posts; optionally fails the first ``failing`` of them."""

    def __init__(self, *, failing: int = 0, error: Exception | None = None) -> None:
        self.sent: list[tuple[str, SuggestionPayload]] = []
        self.failing = failing
        self.error = error or BackendError("BACKEND_REQUEST_FAILED", retryable=True)

    async def __call__(self, session_id: str, payload: SuggestionPayload) -> None:
        if self.failing > 0:
            self.failing -= 1
            raise self.error
        self.sent.append((session_id, payload))


def runner(generator=None, post=None, **kwargs) -> SuggestionRunner:
    generator = generator or Gated("첫 번째 질문입니다.")
    agent = LiveSuggestionAgent(generator, clock=lambda: AT, timeout_seconds=2)
    return SuggestionRunner(agent, session_id="ses_123", post=post or Posts(), **kwargs)


async def settled(subject: SuggestionRunner) -> None:
    """Wait until the queue is drained and the round in flight has posted."""

    await asyncio.wait_for(subject._queue.join(), timeout=5)  # noqa: SLF001


# --- the sink side -----------------------------------------------------------


async def test_the_sink_returns_before_the_model_answers() -> None:
    generator = Gated("첫 번째 질문입니다.")
    generator.gate.clear()
    subject = runner(generator)
    subject.start()

    started = time.perf_counter()
    await subject(question())
    await subject(utterance())
    elapsed = time.perf_counter() - started

    await asyncio.sleep(0.05)
    assert generator.calls == ["qa_utt_q"], "the round is running..."
    assert elapsed < 0.05, "...and the audio path did not wait for it"

    generator.gate.set()
    await settled(subject)
    assert subject.posted == 1
    await subject.stop()


async def test_a_full_queue_drops_rather_than_blocks() -> None:
    subject = runner(max_queue=1)  # never started: nothing drains it

    await subject(question())
    await subject(utterance())

    assert subject.dropped == 1


# --- the task side -----------------------------------------------------------


async def test_a_kept_suggestion_reaches_the_backend_route() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = BackendClient(
        httpx.AsyncClient(
            base_url="https://backend.invalid", transport=httpx.MockTransport(handler)
        ),
        retries=0,
    )
    subject = runner(post=client.post_suggestion)
    subject.start()

    await subject(question())
    await subject(utterance())
    await settled(subject)
    await subject.stop()

    assert [r.url.path for r in requests] == [
        "/internal/v1/sessions/ses_123/suggestions"
    ]
    body = json.loads(requests[0].content)
    assert body["content"] == "첫 번째 질문입니다."
    assert body["evidenceUtteranceIds"] == ["utt_a"]
    assert body["suggestionId"].startswith("sug_")
    assert subject.posted == 1 and subject.rounds == 1


async def test_speech_during_a_round_is_all_ingested_before_the_next_due() -> None:
    generator = Gated("첫 번째 질문입니다.", "두 번째 질문입니다.")
    generator.gate.clear()
    subject = runner(generator)
    subject.start()

    await subject(question())
    await subject(utterance())
    await asyncio.sleep(0.05)
    assert generator.calls == ["qa_utt_q"], "round one is waiting on the model"

    # Eight more words arrive as two utterances while the model is busy.
    await subject(more_words(3, utterance_id="utt_b", seq=2))
    await subject(more_words(5, utterance_id="utt_c", seq=3))
    generator.gate.set()
    await settled(subject)
    await subject.stop()

    assert generator.calls == ["qa_utt_q", "qa_utt_q"], "growth of 8 words: one re-run"
    assert generator.pairs[1].answer_utterance_ids == ["utt_a", "utt_b", "utt_c"], (
        "both queued utterances were ingested before due was asked"
    )
    assert [p.content for _, p in subject.post.sent] == [
        "첫 번째 질문입니다.",
        "두 번째 질문입니다.",
    ]


async def test_a_backend_failure_drops_the_suggestion_and_the_loop_goes_on() -> None:
    posts = Posts(failing=1)
    generator = Gated("첫 번째 질문입니다.", "두 번째 질문입니다.")
    subject = runner(generator, post=posts)
    subject.start()

    await subject(question())
    await subject(utterance())
    await settled(subject)
    await subject(more_words(8, utterance_id="utt_b", seq=2))
    await settled(subject)
    await subject.stop()

    assert subject.post_failures == 1
    assert [p.content for _, p in posts.sent] == ["두 번째 질문입니다."]
    assert subject.rounds == 2


async def test_an_unexpected_error_does_not_end_the_loop(caplog) -> None:
    posts = Posts(failing=1, error=RuntimeError("not a BackendError"))
    generator = Gated("첫 번째 질문입니다.", "두 번째 질문입니다.")
    subject = runner(generator, post=posts)
    subject.start()

    await subject(question())
    await subject(utterance())
    await settled(subject)
    assert subject.running, "the traceback was logged, the task lives"
    await subject(more_words(8, utterance_id="utt_b", seq=2))
    await settled(subject)
    await subject.stop()

    assert [p.content for _, p in posts.sent] == ["두 번째 질문입니다."]
    assert any("suggestion round failed" in r.getMessage() for r in caplog.records)


async def test_a_non_final_or_interviewer_utterance_runs_nothing() -> None:
    generator = Gated("첫 번째 질문입니다.")
    subject = runner(generator)
    subject.start()

    await subject(question())
    await subject(utterance(pass_type="INTERIM"))
    await settled(subject)
    await subject.stop()

    assert generator.calls == []
    assert subject.rounds == 0


# --- stopping ------------------------------------------------------------------


async def test_stop_lets_the_queue_drain_and_the_round_post() -> None:
    subject = runner()
    subject.start()

    await subject(question())
    await subject(utterance())
    await subject.stop()

    assert subject.posted == 1
    assert not subject.running


async def test_stop_cancels_a_round_that_does_not_finish_in_time() -> None:
    generator = Gated("첫 번째 질문입니다.")
    generator.gate.clear()
    subject = runner(generator)
    subject.start()

    await subject(question())
    await subject(utterance())
    await asyncio.sleep(0.05)

    started = time.perf_counter()
    await subject.stop(timeout=0.1)

    assert time.perf_counter() - started < 1
    assert not subject.running
    assert subject.posted == 0


async def test_stopping_a_runner_that_never_started_is_fine() -> None:
    subject = runner()
    await subject.stop()
    assert not subject.running


def test_a_queue_must_hold_something() -> None:
    with pytest.raises(ValueError):
        runner(max_queue=0)
