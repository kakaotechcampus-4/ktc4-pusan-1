"""Timeline pipeline without a model: selection, verification, agent states."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from irya_ai.pipeline.qa_segmentation import segment_qa
from irya_ai.schemas import (
    MomentCitationDraft,
    MomentDraft,
    QAPair,
    TimelineDraft,
    TranscriptSnapshot,
    TranscriptStage,
    Utterance,
)
from irya_ai.timeline import (
    ExtractiveTimelineGenerator,
    FakeTimelineGenerator,
    ReviewTimelineAgent,
    TimelineError,
    build_timeline,
    select_qa_pairs,
    snapshot_from_chunks,
)

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
CHUNKS = SAMPLES / "chunks_backend_junior_01.json"
_UTTERANCES = TypeAdapter(list[Utterance])


@pytest.fixture
def chunks() -> list[Utterance]:
    return _UTTERANCES.validate_json(CHUNKS.read_text(encoding="utf-8"))


@pytest.fixture
def snapshot(chunks: list[Utterance]) -> TranscriptSnapshot:
    return snapshot_from_chunks(chunks)


@pytest.fixture
def selected(snapshot: TranscriptSnapshot) -> list[QAPair]:
    return select_qa_pairs(segment_qa(snapshot.final_utterances()).qa_pairs)


def draft(qa_id: str, label: str, answer: str, uid: str, quote: str) -> MomentDraft:
    return MomentDraft(
        qa_id=qa_id,
        label=label,
        answer=answer,
        citations=[MomentCitationDraft(utterance_id=uid, quote=quote)],
    )


# --- input -----------------------------------------------------------------


def test_sample_chunks_are_final_utterances_of_one_session(
    chunks: list[Utterance],
) -> None:
    assert len(chunks) > 20
    assert all(u.is_final for u in chunks)
    assert len({u.session_id for u in chunks}) == 1
    # No word timings: the STT chunk contract (#36) does not provide them.
    assert all(not u.words for u in chunks)


def test_snapshot_from_chunks_keeps_last_final_revision(
    chunks: list[Utterance],
) -> None:
    first = chunks[0]
    revised = first.model_copy(update={"content": first.content + " (수정)"})
    snapshot = snapshot_from_chunks([*chunks, revised])

    finals = snapshot.final_utterances()
    assert len(finals) == len(chunks)
    assert finals[0].content.endswith("(수정)")
    assert snapshot.stage is TranscriptStage.LIVE


def test_snapshot_from_chunks_rejects_mixed_sessions(chunks: list[Utterance]) -> None:
    other = chunks[1].model_copy(update={"session_id": "ses_other"})
    with pytest.raises(ValueError, match="sessions"):
        snapshot_from_chunks([chunks[0], other])
    with pytest.raises(ValueError, match="no utterances"):
        snapshot_from_chunks([])


def test_mid_sentence_chunk_split_still_forms_one_answer(
    snapshot: TranscriptSnapshot,
) -> None:
    """The sample splits one candidate sentence across two chunks (5 s cap)."""

    pairs = segment_qa(snapshot.final_utterances()).qa_pairs
    split_pair = next(p for p in pairs if "쿼리 파라미터" in p.answer_text)
    assert len(split_pair.answer_utterance_ids) >= 2
    assert "프론트에서 필요한 필드를" in split_pair.answer_text


# --- selection -------------------------------------------------------------


def _pair(qa_id: str, start_ms: int, words: int, answered: bool = True) -> QAPair:
    return QAPair(
        qa_id=qa_id,
        session_id="ses_x",
        question_utterance_ids=[f"q_{qa_id}"],
        answer_utterance_ids=[f"a_{qa_id}"] if answered else [],
        start_ms=start_ms,
        end_ms=start_ms + 1000,
        answer_word_count=words if answered else 0,
        question_text="q",
        answer_text="a" if answered else "",
    )


def test_select_drops_unanswered_and_keeps_order() -> None:
    pairs = [_pair("a", 0, 5), _pair("b", 10, 0, answered=False), _pair("c", 20, 7)]

    assert [p.qa_id for p in select_qa_pairs(pairs)] == ["a", "c"]


def test_select_caps_by_answer_length_but_stays_chronological() -> None:
    pairs = [_pair(f"p{i}", i * 10, words) for i, words in enumerate([3, 50, 1, 40, 9])]

    chosen = select_qa_pairs(pairs, max_moments=3)

    assert [p.qa_id for p in chosen] == ["p1", "p3", "p4"]
    with pytest.raises(ValueError):
        select_qa_pairs(pairs, max_moments=0)


def test_sample_has_between_five_and_eight_selected(selected: list[QAPair]) -> None:
    assert 5 <= len(selected) <= 8


# --- verification ----------------------------------------------------------


def test_verified_draft_becomes_moment_with_code_owned_fields(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    pair = selected[1]
    uid = pair.answer_utterance_ids[0]
    source = next(u for u in snapshot.final_utterances() if u.utterance_id == uid)
    quote = source.content[:12]
    d = draft(
        pair.qa_id,
        " 캐시  설계 ",
        "Redis 캐시를 조회 API 앞에 뒀다고 답했다.",
        uid,
        quote,
    )

    moments, rejections = build_timeline(
        snapshot, selected, TimelineDraft(moments=[d]), model="test"
    )

    assert rejections == []
    (m,) = moments
    assert m.moment_id == f"mom_{pair.qa_id}"
    assert m.at_ms == pair.start_ms and m.end_ms == pair.end_ms
    assert m.question == pair.question_text  # verbatim, not from the model
    assert m.label == "캐시 설계"  # whitespace collapsed
    assert m.evidence[0].t_ms == source.start_ms  # no word timings -> start
    assert m.to_frontend() == {
        "id": m.moment_id,
        "atSec": pair.start_ms / 1000,
        "label": "캐시 설계",
        "question": pair.question_text,
        "answer": "Redis 캐시를 조회 API 앞에 뒀다고 답했다.",
    }


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda d, p, u, q: draft("qa_nope", "라벨", "답", u, q), "not among"),
        (lambda d, p, u, q: draft(p, "   ", "답", u, q), "empty label"),
        (
            lambda d, p, u, q: draft(p, "열세글자가넘는아주긴라벨입니다", "답", u, q),
            "label longer",
        ),
        (lambda d, p, u, q: draft(p, "라벨", " ", u, q), "empty answer"),
        (lambda d, p, u, q: draft(p, "라벨", "답", "utt_999", q), "unknown utterance"),
        (lambda d, p, u, q: draft(p, "라벨", "답", u, " "), "empty quote"),
        (
            lambda d, p, u, q: draft(p, "라벨", "답", u, q.lower().replace("R", "r")),
            "quote not found",
        ),
        (
            lambda d, p, u, q: draft(p, "라벨", "응답 시간을 70% 줄였다", u, q),
            "numbers not in evidence",
        ),
        (
            lambda d, p, u, q: MomentDraft(
                qa_id=p, label="라벨", answer="답", citations=[]
            ),
            "no citation",
        ),
    ],
)
def test_invalid_drafts_are_rejected_with_reason(
    snapshot: TranscriptSnapshot, selected: list[QAPair], mutate, reason: str
) -> None:
    pair = selected[1]
    uid = pair.answer_utterance_ids[0]
    source = next(u for u in snapshot.final_utterances() if u.utterance_id == uid)
    # Start the quote at "Redis": the case-change case needs an ASCII letter.
    quote = source.content[source.content.index("Redis") :][:12]

    moments, rejections = build_timeline(
        snapshot,
        selected,
        TimelineDraft(moments=[mutate(None, pair.qa_id, uid, quote)]),
        model="test",
    )

    assert moments == []
    assert len(rejections) == 1
    assert reason in rejections[0]


def test_citation_must_belong_to_that_answer(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    """A real candidate quote from a different question is still rejected."""

    pair, other = selected[1], selected[2]
    uid = other.answer_utterance_ids[0]
    source = next(u for u in snapshot.final_utterances() if u.utterance_id == uid)

    _, rejections = build_timeline(
        snapshot,
        selected,
        TimelineDraft(
            moments=[draft(pair.qa_id, "라벨", "답", uid, source.content[:8])]
        ),
        model="test",
    )

    assert "not part of this answer" in rejections[0]


def test_interviewer_utterance_cannot_be_evidence(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    pair = selected[0]
    q_uid = pair.question_utterance_ids[0]
    forged = pair.model_copy(update={"answer_utterance_ids": [q_uid]})

    _, rejections = build_timeline(
        snapshot,
        [forged],
        TimelineDraft(moments=[draft(pair.qa_id, "라벨", "답", q_uid, "안녕하세요")]),
        model="test",
    )

    assert "not candidate speech" in rejections[0]


def test_duplicates_use_first_and_output_follows_question_order(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    sources = {u.utterance_id: u for u in snapshot.final_utterances()}

    def ok(pair: QAPair, label: str) -> MomentDraft:
        uid = pair.answer_utterance_ids[0]
        return draft(pair.qa_id, label, "답변", uid, sources[uid].content[:6])

    drafts = [ok(selected[2], "셋째"), ok(selected[0], "첫째"), ok(selected[0], "중복")]
    moments, rejections = build_timeline(
        snapshot, selected, TimelineDraft(moments=drafts), model="test"
    )

    assert [m.label for m in moments] == ["첫째", "셋째"]
    assert rejections == [f"{selected[0].qa_id}: duplicate draft"]


# --- generators and agent ----------------------------------------------------


def test_extractive_generator_quotes_first_sentence(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    sources = {u.utterance_id: u for u in snapshot.final_utterances()}
    result = asyncio.run(ExtractiveTimelineGenerator().generate(selected, sources))

    assert [d.qa_id for d in result.moments] == [p.qa_id for p in selected]
    first = result.moments[0]
    assert first.answer == "안녕하세요, 정민호입니다."
    assert first.citations[0].quote == first.answer
    assert len(first.label) <= 12


async def test_agent_completed_with_extractive_baseline(
    snapshot: TranscriptSnapshot,
) -> None:
    result = await ReviewTimelineAgent(
        ExtractiveTimelineGenerator(), model="extractive-baseline"
    ).run(snapshot)

    assert result.status == "completed"
    assert result.rejected_moment_count == 0
    assert len(result.moments) == len(result.selected_qa_ids) == 7
    assert result.duration_ms == max(u.end_ms for u in snapshot.final_utterances())
    assert "PROVISIONAL_TRANSCRIPT" in result.warnings
    assert result.model == "extractive-baseline"
    assert [m["atSec"] for m in result.frontend_moments()] == sorted(
        m["atSec"] for m in result.frontend_moments()
    )


async def test_agent_partial_when_some_drafts_fail(
    snapshot: TranscriptSnapshot, selected: list[QAPair]
) -> None:
    sources = {u.utterance_id: u for u in snapshot.final_utterances()}
    uid = selected[0].answer_utterance_ids[0]
    good = draft(
        selected[0].qa_id, "자기소개", "소개했다", uid, sources[uid].content[:6]
    )
    bad = draft(selected[1].qa_id, "캐시", "설계했다", uid, "없는 인용문")
    fake = FakeTimelineGenerator(TimelineDraft(moments=[good, bad]))

    result = await ReviewTimelineAgent(fake, model="fake").run(snapshot)

    assert result.status == "partial"
    assert "UNGROUNDED_MOMENTS_REMOVED" in result.warnings
    assert "FEWER_THAN_FIVE_MOMENTS" in result.warnings
    assert result.rejected_moment_count == 1
    assert fake.calls == [[p.qa_id for p in selected]]


async def test_agent_failed_when_nothing_grounds_but_keeps_qa(
    snapshot: TranscriptSnapshot,
) -> None:
    fake = FakeTimelineGenerator(TimelineDraft(moments=[]))

    result = await ReviewTimelineAgent(fake).run(snapshot)

    assert result.status == "failed"
    assert result.error is not None and result.error.code == "NO_GROUNDED_MOMENTS"
    assert result.moments == []
    assert len(result.qa_pairs) == 7  # the rule-based structure survives


async def test_agent_maps_generator_errors_and_timeouts(
    snapshot: TranscriptSnapshot,
) -> None:
    class Failing:
        async def generate(self, pairs, sources):
            raise TimelineError("LLM_RATE_LIMITED", retryable=True)

    class Slow:
        async def generate(self, pairs, sources):
            await asyncio.sleep(1)
            return TimelineDraft(moments=[])

    failed = await ReviewTimelineAgent(Failing()).run(snapshot)
    assert failed.status == "failed"
    assert failed.error.code == "LLM_RATE_LIMITED" and failed.error.retryable

    timed_out = await ReviewTimelineAgent(Slow(), timeout_seconds=0.01).run(snapshot)
    assert timed_out.status == "failed"
    assert timed_out.error.code == "LLM_TIMEOUT"


async def test_agent_empty_when_no_answered_question() -> None:
    u = Utterance(
        utterance_id="utt_000",
        session_id="ses_x",
        track_id="trk_interviewer",
        speaker="INTERVIEWER",
        seq=0,
        start_ms=0,
        end_ms=1000,
        content="자기소개 부탁드립니다.",
    )
    fake = FakeTimelineGenerator(TimelineDraft(moments=[]))

    result = await ReviewTimelineAgent(fake).run(snapshot_from_chunks([u]))

    assert result.status == "empty"
    assert fake.calls == []  # no model call when there is nothing to label


def test_result_json_is_camel_case(snapshot: TranscriptSnapshot) -> None:
    result = asyncio.run(
        ReviewTimelineAgent(ExtractiveTimelineGenerator()).run(snapshot)
    )
    data = json.loads(result.model_dump_json(by_alias=True))

    assert "rejectedMomentCount" in data
    assert set(data["moments"][0]) == {
        "momentId",
        "qaId",
        "atMs",
        "endMs",
        "label",
        "question",
        "answer",
        "evidence",
    }
    assert set(data["moments"][0]["evidence"][0]) == {
        "utteranceId",
        "quote",
        "speaker",
        "startMs",
        "endMs",
        "tMs",
    }
