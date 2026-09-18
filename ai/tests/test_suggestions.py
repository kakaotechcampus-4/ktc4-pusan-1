"""Live suggestions without a model: the trigger, the grounding gate, the caps."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import TypeAdapter

from irya_ai.backend import BackendClient
from irya_ai.pipeline.qa_segmentation import segment_qa
from irya_ai.schemas import (
    CitationDraft,
    QAPair,
    SpeakerRole,
    SuggestionBatchDraft,
    SuggestionDraft,
    Utterance,
    suggestion_payload,
)
from irya_ai.suggestions import (
    DEFAULT_MAX_PER_ANSWER,
    ExtractiveSuggestionGenerator,
    FakeSuggestionGenerator,
    LiveSuggestionAgent,
    SuggestionError,
    build_suggestions,
)

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
CHUNKS = SAMPLES / "chunks_backend_junior_01.json"
_UTTERANCES = TypeAdapter(list[Utterance])

AT = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
ANSWER = "결제 API를 맡아서 초당 300건까지 처리되도록 캐시를 넣었습니다."


@pytest.fixture
def chunks() -> list[Utterance]:
    return _UTTERANCES.validate_json(CHUNKS.read_text(encoding="utf-8"))


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


def pair_for(*utterances: Utterance, question: str = "어떤 일을 하셨나요?") -> QAPair:
    return QAPair(
        qa_id="qa_utt_q",
        session_id="ses_123",
        question_utterance_ids=["utt_q"],
        answer_utterance_ids=[u.utterance_id for u in utterances],
        start_ms=0,
        end_ms=max(u.end_ms for u in utterances),
        answer_word_count=sum(len(u.content.split()) for u in utterances),
        question_text=question,
        answer_text=" ".join(u.content for u in utterances),
    )


def draft(
    content: str = "캐시를 어디에 두셨는지 더 여쭤보세요.",
    *,
    reason: str = "지원자가 캐시를 언급했습니다.",
    utterance_id: str = "utt_a",
    quote: str = "캐시를 넣었습니다",
) -> SuggestionDraft:
    return SuggestionDraft(
        content=content,
        reason=reason,
        evidence=[CitationDraft(utterance_id=utterance_id, quote=quote)],
    )


def build(*drafts: SuggestionDraft, **kwargs):
    source = utterance()
    return build_suggestions(
        pair_for(source),
        SuggestionBatchDraft(suggestions=list(drafts)),
        {source.utterance_id: source},
        generated_at=AT,
        **kwargs,
    )


# --- verification ----------------------------------------------------------


def test_a_quoted_suggestion_survives_and_carries_only_the_ids() -> None:
    kept, rejections = build(draft())

    assert rejections == []
    assert [s.content for s in kept] == ["캐시를 어디에 두셨는지 더 여쭤보세요."]
    assert kept[0].evidence_utterance_ids == ["utt_a"]
    assert kept[0].qa_id == "qa_utt_q"
    assert kept[0].generated_at == AT


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (draft(quote="레디스를 붙였습니다"), "1: quote not found in utt_a"),
        (draft(utterance_id="utt_zz"), "1: unknown utterance utt_zz"),
        (draft(quote="   "), "1: empty quote"),
    ],
)
def test_a_citation_that_does_not_hold_up_drops_the_whole_suggestion(
    bad: SuggestionDraft, reason: str
) -> None:
    kept, rejections = build(bad)

    assert kept == []
    assert rejections == [reason]


def test_a_suggestion_with_no_evidence_at_all_is_dropped() -> None:
    kept, rejections = build(
        SuggestionDraft(content="더 물어보세요.", reason="감으로", evidence=[])
    )

    assert kept == []
    assert rejections == ["1: no evidence"]


def test_evidence_from_another_answer_is_not_this_answer_s_evidence() -> None:
    """The utterance exists and is the candidate's - but not in this Q&A."""

    source = utterance()
    other = utterance(utterance_id="utt_b", seq=3, start_ms=20_000, end_ms=25_000)

    kept, rejections = build_suggestions(
        pair_for(source),
        SuggestionBatchDraft(suggestions=[draft(utterance_id="utt_b")]),
        {source.utterance_id: source, other.utterance_id: other},
        generated_at=AT,
    )

    assert kept == []
    assert rejections == ["1: evidence utt_b is not part of this answer"]


def test_the_interviewer_s_own_words_are_not_candidate_evidence() -> None:
    asked = utterance(
        utterance_id="utt_q",
        speaker=SpeakerRole.INTERVIEWER,
        track_id="trk_interviewer",
        seq=0,
        start_ms=0,
        end_ms=900,
        content="캐시를 넣었습니다만 왜 그러셨나요?",
    )
    source = utterance()
    pair = pair_for(source)
    pair.answer_utterance_ids = ["utt_a", "utt_q"]

    kept, rejections = build_suggestions(
        pair,
        SuggestionBatchDraft(suggestions=[draft(utterance_id="utt_q")]),
        {"utt_a": source, "utt_q": asked},
        generated_at=AT,
    )

    assert kept == []
    assert rejections == ["1: evidence utt_q is not candidate speech"]


def test_a_number_the_candidate_never_said_drops_the_suggestion() -> None:
    kept, rejections = build(draft(content="초당 5000건까지 되는지 여쭤보세요."))

    assert kept == []
    assert rejections == ["1: numbers not in evidence: 5000"]


def test_a_number_inside_the_quoted_evidence_is_allowed() -> None:
    kept, _ = build(
        draft(
            content="초당 300건이 어떻게 측정됐는지 여쭤보세요.",
            quote="초당 300건까지 처리되도록 캐시를 넣었습니다",
        )
    )

    assert len(kept) == 1


def test_a_number_the_interviewer_said_counts_as_source_text() -> None:
    source = utterance()
    kept, rejections = build_suggestions(
        pair_for(source, question="초당 1000건 규모도 다뤄보셨나요?"),
        SuggestionBatchDraft(
            suggestions=[draft(content="초당 1000건은 어떻게 다르냐고 여쭤보세요.")]
        ),
        {source.utterance_id: source},
        generated_at=AT,
    )

    assert rejections == []
    assert len(kept) == 1


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (draft(content="   "), "1: empty content"),
        (draft(content="설명" * 100), "1: content longer than 120 chars"),
        (draft(reason="  "), "1: empty reason"),
        (draft(reason="이유" * 50), "1: reason longer than 80 chars"),
    ],
)
def test_a_suggestion_the_panel_cannot_show_is_dropped(
    bad: SuggestionDraft, reason: str
) -> None:
    kept, rejections = build(bad)

    assert kept == []
    assert rejections == [reason]


def test_the_same_question_twice_is_only_offered_once() -> None:
    kept, rejections = build(draft(), draft())

    assert len(kept) == 1
    assert rejections == ["2: duplicate of an earlier suggestion"]


def test_a_question_already_offered_this_session_does_not_come_back() -> None:
    kept, rejections = build(
        draft(), seen_contents=frozenset({"캐시를 어디에 두셨는지 더 여쭤보세요."})
    )

    assert kept == []
    assert rejections == ["1: duplicate of an earlier suggestion"]


def test_the_per_answer_cap_rejects_the_overflow_rather_than_hiding_it() -> None:
    kept, rejections = build(
        draft(), draft(content="테스트는 어떻게 하셨는지 여쭤보세요."), max_per_answer=1
    )

    assert len(kept) == 1
    assert rejections == ["2: over the 1 per answer limit"]


def test_ids_are_numbered_over_what_was_kept_not_what_was_drafted() -> None:
    kept, _ = build(
        draft(quote="있지도 않은 말"), draft(content="캐시 만료는 어떻게 하셨나요?")
    )

    assert [s.question_id for s in kept] == ["sug_qa_utt_q_1"]


# --- the extractive baseline -----------------------------------------------


async def test_the_extractive_baseline_quotes_the_candidate_verbatim() -> None:
    source = utterance()
    pair = pair_for(source)
    batch = await ExtractiveSuggestionGenerator().generate(
        pair, {source.utterance_id: source}
    )

    kept, rejections = build_suggestions(
        pair, batch, {source.utterance_id: source}, generated_at=AT
    )

    assert rejections == []
    assert len(kept) == 1
    assert kept[0].evidence_utterance_ids == ["utt_a"]


async def test_the_extractive_baseline_stays_within_the_panel_s_width() -> None:
    source = utterance(content="그래서 " * 60 + "했습니다.")
    pair = pair_for(source)
    batch = await ExtractiveSuggestionGenerator().generate(
        pair, {source.utterance_id: source}
    )

    kept, rejections = build_suggestions(
        pair, batch, {source.utterance_id: source}, generated_at=AT
    )

    assert rejections == []
    assert len(kept[0].content) <= 120


async def test_the_extractive_baseline_has_nothing_to_say_about_no_answer() -> None:
    pair = QAPair(
        qa_id="qa_utt_q",
        session_id="ses_123",
        question_utterance_ids=["utt_q"],
        answer_utterance_ids=[],
        start_ms=0,
        end_ms=900,
        question_text="어떤 일을 하셨나요?",
    )

    batch = await ExtractiveSuggestionGenerator().generate(pair, {})

    assert batch.suggestions == []


# --- the live agent --------------------------------------------------------


def agent(**kwargs) -> LiveSuggestionAgent:
    generator = kwargs.pop("generator", None) or FakeSuggestionGenerator(
        SuggestionBatchDraft(suggestions=[draft()])
    )
    return LiveSuggestionAgent(generator, clock=lambda: AT, **kwargs)


async def test_the_agent_waits_for_the_answer_then_fires_once() -> None:
    asked = utterance(
        utterance_id="utt_q",
        speaker=SpeakerRole.INTERVIEWER,
        track_id="trk_interviewer",
        seq=0,
        start_ms=0,
        end_ms=900,
        content="어떤 일을 하셨는지 말씀해주세요.",
    )
    short = utterance(utterance_id="utt_s", seq=1, start_ms=1_000, end_ms=2_000)
    short = short.model_copy(update={"content": "네."})
    answer = utterance(utterance_id="utt_a", seq=2, start_ms=2_000, end_ms=9_000)
    more = utterance(utterance_id="utt_m", seq=3, start_ms=9_000, end_ms=12_000)
    more = more.model_copy(update={"content": "그리고 모니터링도 붙였습니다."})

    live = agent()

    assert await live.observe(asked) is None, "a question alone is not a moment"
    assert await live.observe(short) is None, "a two-word answer is not one either"

    result = await live.observe(answer)
    assert result is not None
    assert result.status == "completed"
    assert len(result.suggestions) == 1

    assert await live.observe(more) is None, "one round per question"
    assert live.generator.calls == [result.qa_id]


async def test_a_non_final_utterance_never_triggers_a_round() -> None:
    live = agent()
    partial = utterance(pass_type="INTERIM")

    assert await live.observe(partial) is None
    assert live.generator.calls == []


async def test_a_round_that_drops_everything_says_so_instead_of_staying_silent() -> (
    None
):
    source = utterance()
    live = agent(
        generator=FakeSuggestionGenerator(
            SuggestionBatchDraft(suggestions=[draft(quote="있지도 않은 말")])
        )
    )
    await live.observe(
        utterance(
            utterance_id="utt_q",
            speaker=SpeakerRole.INTERVIEWER,
            track_id="trk_interviewer",
            seq=0,
            start_ms=0,
            end_ms=900,
            content="어떤 일을 하셨는지 말씀해주세요.",
        )
    )
    result = await live.observe(source)

    assert result is not None
    assert result.suggestions == []
    assert result.status == "partial"
    assert result.warnings == ["UNGROUNDED_SUGGESTIONS_REMOVED"]
    assert live.sent_count == 0


async def test_a_generator_failure_becomes_a_typed_error_not_an_exception() -> None:
    class Failing:
        async def generate(self, pair, sources, context=None):
            raise SuggestionError("LLM_RATE_LIMITED", retryable=True)

    live = agent(generator=Failing())
    source = utterance()
    result = await live.suggest(pair_for(source))

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "LLM_RATE_LIMITED"
    assert result.error.retryable is True


async def test_a_generator_that_hangs_times_out_as_a_retryable_error() -> None:
    class Hanging:
        async def generate(self, pair, sources, context=None):
            import asyncio

            await asyncio.sleep(10)
            raise AssertionError("unreachable")

    live = agent(generator=Hanging(), timeout_seconds=0.01)
    source = utterance()
    result = await live.suggest(pair_for(source))

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "LLM_TIMEOUT"
    assert result.error.retryable is True


async def test_the_session_budget_is_a_stop_not_a_slowdown() -> None:
    live = agent(max_per_session=1)
    source = utterance()
    live._sources[source.utterance_id] = source

    first = await live.suggest(pair_for(source))
    assert len(first.suggestions) == 1

    second = await live.suggest(pair_for(source))
    assert second.suggestions == []
    assert second.status == "empty"
    assert second.warnings == ["SESSION_LIMIT_REACHED"]


async def test_a_session_never_offers_the_same_question_twice() -> None:
    live = agent()
    source = utterance()
    live._sources[source.utterance_id] = source

    await live.suggest(pair_for(source))
    again = await live.suggest(pair_for(source))

    assert again.suggestions == []
    assert again.rejections == ["1: duplicate of an earlier suggestion"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": 0},
        {"max_per_answer": 0},
        {"max_per_session": 0},
        {"min_answer_words": 0},
    ],
)
def test_a_cap_that_means_nothing_is_refused_at_construction(kwargs) -> None:
    with pytest.raises(ValueError):
        agent(**kwargs)


# --- end to end over the sample transcript ---------------------------------


async def test_the_sample_interview_produces_grounded_suggestions(
    chunks: list[Utterance],
) -> None:
    """완료 조건: 시뮬레이터 전사를 흘려 넣으면 근거 있는 꼬리질문이 나온다."""

    live = LiveSuggestionAgent(ExtractiveSuggestionGenerator(), clock=lambda: AT)
    by_id = {u.utterance_id: u for u in chunks}
    results = [r for u in chunks if (r := await live.observe(u)) is not None]

    assert results, "the sample interview has answers worth following up on"
    # One round per Q&A at most. ``segment_qa`` re-runs over every final on
    # each feed, so a pair that gets re-cut - a backchannel "네." kept at feed
    # time and folded into the answer on the next pass - must not come back
    # under a new ``qa_id`` and earn a second round.
    assert len({r.qa_id for r in results}) == len(results)
    suggestions = [s for r in results for s in r.suggestions]
    assert suggestions

    pairs = {p.qa_id: p for p in segment_qa(chunks).qa_pairs}
    for s in suggestions:
        assert s.evidence_utterance_ids
        for uid in s.evidence_utterance_ids:
            assert by_id[uid].speaker is SpeakerRole.CANDIDATE
            assert uid in pairs[s.qa_id].answer_utterance_ids
        assert len(s.content) <= 120


async def test_the_sample_interview_stays_inside_its_own_budget(
    chunks: list[Utterance],
) -> None:
    live = LiveSuggestionAgent(
        ExtractiveSuggestionGenerator(), clock=lambda: AT, max_per_session=3
    )
    results = [r for u in chunks if (r := await live.observe(u)) is not None]
    total = sum(len(r.suggestions) for r in results)

    assert total == 3
    assert live.sent_count == 3
    assert DEFAULT_MAX_PER_ANSWER == 2


# --- from the agent to Backend ---------------------------------------------


def recording_client(seen: list[httpx.Request]) -> BackendClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    return BackendClient(
        httpx.AsyncClient(
            base_url="https://backend.invalid",
            transport=httpx.MockTransport(handler),
        ),
        backoff_seconds=0.0,
    )


async def send_all(
    live: LiveSuggestionAgent, chunks: list[Utterance], seen: list[httpx.Request]
) -> list:
    """Run the interview and post whatever the agent hands back, as a caller would."""

    client = recording_client(seen)
    sent = []
    for chunk in chunks:
        result = await live.observe(chunk)
        if result is None:
            continue
        for question in result.suggestions:
            await client.post_suggestion(
                question.session_id, suggestion_payload(question)
            )
            sent.append(question)
    return sent


async def test_the_sample_interview_s_suggestions_reach_the_agreed_route(
    chunks: list[Utterance],
) -> None:
    """완료 조건: 전사를 흘려 넣으면 꼬리질문이 생성되고 합의된 경로로 전송된다.

    The two halves are tested apart elsewhere - the agent up to
    :class:`SuggestedQuestion`, the client from a hand-built payload. This is
    the join, so a rename between them fails here rather than at an interview.
    """

    seen: list[httpx.Request] = []
    live = LiveSuggestionAgent(ExtractiveSuggestionGenerator(), clock=lambda: AT)

    sent = await send_all(live, chunks, seen)

    assert sent
    assert len(seen) == len(sent)
    for request, question in zip(seen, sent, strict=True):
        assert request.method == "POST"
        assert request.url.path == "/internal/v1/sessions/ses_sample_01/suggestions"
        body = json.loads(request.content)
        assert set(body) == {"suggestionId", "type", "content", "evidenceUtteranceIds"}
        assert body["type"] == "FOLLOW_UP"
        assert body["suggestionId"] == question.question_id
        assert body["content"] == question.content
        assert body["evidenceUtteranceIds"] == question.evidence_utterance_ids
        assert body["evidenceUtteranceIds"]


@pytest.mark.parametrize(
    "ungrounded",
    [
        draft(utterance_id="utt_zz"),
        draft(utterance_id="utt_003", quote="레디스 클러스터를 직접 운영했습니다"),
    ],
    ids=["an id nobody has", "a quote nobody said"],
)
async def test_an_ungrounded_suggestion_never_reaches_the_wire(
    chunks: list[Utterance], ungrounded: SuggestionDraft
) -> None:
    """완료 조건: 근거 없는 꼬리질문은 전송되지 않는다 - 전송 경계에서 확인."""

    seen: list[httpx.Request] = []
    generator = FakeSuggestionGenerator(SuggestionBatchDraft(suggestions=[ungrounded]))
    live = LiveSuggestionAgent(generator, clock=lambda: AT)

    sent = await send_all(live, chunks, seen)

    assert generator.calls, "the rounds ran; the gate is what stopped the send"
    assert sent == []
    assert seen == []
