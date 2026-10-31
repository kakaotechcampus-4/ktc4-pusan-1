"""Synthetic input only; every sentence must stand on an adopted finding."""

import asyncio

import pytest

from irya_ai.report import (
    ExtractiveReportGenerator,
    FakeReportGenerator,
    ReportAgent,
    ReportError,
    build_report,
)
from irya_ai.schemas.report import (
    CompetencyReportDraft,
    ReportContext,
    ReportDraft,
    ReportResult,
    SentenceDraft,
)
from irya_ai.schemas.wire import report_payload

QUOTE = "결제 멱등키 중복 방지를 설계·구현"
TRANSCRIPT = "APM으로 먼저 어디가 느린지 봤고, 캐시를 5분으로 걸었습니다"


def context(**changes) -> ReportContext:
    data = {
        "interviewId": "int_test",
        "sessionId": "ses_test",
        "summary": {"overview": "캐시와 결제를 이야기한 면접.", "keyPoints": ["캐시"]},
        "competencies": [
            {"competencyId": "cmp_api", "name": "주문·결제 API", "required": True},
            {"competencyId": "cmp_db", "name": "DB 튜닝", "required": False},
        ],
        "findings": [
            {
                "findingId": "fnd_cache",
                "competencyId": "cmp_api",
                "findingType": "COMPETENCY_EVIDENCE",
                "text": "캐시로 응답을 줄였다고 설명함",
                "quote": None,
                "transcript": TRANSCRIPT,
            },
            {
                "findingId": "fnd_idem",
                "competencyId": "cmp_api",
                "findingType": "CLAIM_CONTRADICTED",
                "text": "설계는 선배가 했다고 답함",
                "quote": QUOTE,
                "transcript": "설계는 선배가 잡아 주셨습니다",
            },
            {
                "findingId": "fnd_free",
                "competencyId": None,
                "findingType": "CLAIM_VERIFIED",
                "text": "주장과 같은 내용을 답함",
                "quote": "2년간 운영",
                "transcript": "2년 동안 운영했습니다",
            },
        ],
    }
    data.update(changes)
    return ReportContext.model_validate(data)


def sentence(**changes) -> SentenceDraft:
    return SentenceDraft.model_validate(
        {
            "text": "캐시 도입 경험을 구체적으로 설명함",
            "finding_id": "fnd_cache",
            **changes,
        }
    )


def block(**changes) -> CompetencyReportDraft:
    return CompetencyReportDraft.model_validate(
        {
            "competency_id": "cmp_api",
            "confirmed": [sentence()],
            "unconfirmed": [
                sentence(
                    text="멱등키 설계는 본인이 하지 않았다고 답함",
                    finding_id="fnd_idem",
                )
            ],
            "next_questions": ["캐시 무효화 기준은 무엇이었는지"],
            **changes,
        }
    )


def draft(
    *blocks: CompetencyReportDraft, overview: str = "전체 요약 세 줄."
) -> ReportDraft:
    return ReportDraft(overview=overview, competencies=list(blocks) or [block()])


def test_backend_review_row_spelling_is_read_and_extra_keys_are_ignored():
    ctx = context(
        findings=[
            {
                "id": "fnd_cache",
                "type": "COMPETENCY_EVIDENCE",
                "competency": "cmp_api",
                "source": "면접 답변",
                "quote": None,
                "transcript": TRANSCRIPT,
                "rationale": "캐시로 응답을 줄였다고 설명함",
                "atSec": 72.4,
                "state": "ADOPTED",
            }
        ],
        competencies=[{"competencyId": "cmp_api", "name": "API", "state": "PARTIAL"}],
    )
    assert ctx.findings[0].finding_id == "fnd_cache"
    assert ctx.findings[0].text == "캐시로 응답을 줄였다고 설명함"
    assert ctx.findings[0].transcript == TRANSCRIPT
    assert ctx.competencies[0].state == "PARTIAL"


def test_ai_finding_spelling_is_read_too():
    ctx = context(
        findings=[
            {
                "findingId": "fnd_cache",
                "sessionId": "ses_test",
                "type": "COMPETENCY_EVIDENCE",
                "competencyId": "cmp_api",
                "evidenceUtteranceId": "utt_1",
                "evidenceQuote": TRANSCRIPT,
                "evidenceTMs": 72400,
                "summary": "캐시로 응답을 줄였다고 설명함",
                "state": "ADOPTED",
            }
        ]
    )
    assert ctx.findings[0].transcript == TRANSCRIPT
    assert ctx.findings[0].text == "캐시로 응답을 줄였다고 설명함"


def test_every_competency_comes_back_in_context_order():
    overview, reports, rejected = build_report(context(), draft())
    assert rejected == []
    assert overview == "전체 요약 세 줄."
    assert [r.competency_id for r in reports] == ["cmp_api", "cmp_db"]
    assert [s.finding_id for s in reports[0].confirmed] == ["fnd_cache"]
    assert [s.finding_id for s in reports[0].unconfirmed] == ["fnd_idem"]
    assert reports[0].next_questions == ["캐시 무효화 기준은 무엇이었는지"]
    assert reports[1].confirmed == [] and reports[1].unconfirmed == []
    assert reports[1].next_questions == []


def test_a_finding_without_a_competency_may_be_cited_anywhere():
    item = sentence(text="운영 경험을 답함", finding_id="fnd_free")
    _, reports, rejected = build_report(
        context(),
        draft(block(competency_id="cmp_db", confirmed=[item], unconfirmed=[])),
    )
    assert rejected == []
    assert [s.finding_id for s in reports[1].confirmed] == ["fnd_free"]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"finding_id": "fnd_missing"}, "finding not adopted"),
        ({"finding_id": "fnd_idem"}, "finding type does not fit this list"),
        ({"text": ""}, "invalid sentence length"),
        ({"text": "가" * 201}, "invalid sentence length"),
        (
            {"text": "응답을 99% 줄였다고 설명함"},
            "sentence contains unsupported numbers",
        ),
    ],
)
def test_bad_sentences_are_dropped_without_echoing_text(changes, reason):
    _, reports, rejected = build_report(
        context(), draft(block(confirmed=[sentence(**changes)], unconfirmed=[]))
    )
    assert reports[0].confirmed == []
    assert rejected == [f"cmp_api confirmed 1: {reason}"]
    assert "99%" not in rejected[0]
    assert "fnd_missing" not in rejected[0]


def test_numbers_in_the_finding_quote_or_transcript_are_supported():
    item = sentence(text="캐시를 5분으로 두었다고 설명함")
    _, reports, rejected = build_report(
        context(), draft(block(confirmed=[item], unconfirmed=[]))
    )
    assert rejected == []
    assert reports[0].confirmed[0].text == "캐시를 5분으로 두었다고 설명함"


def test_a_finding_filed_under_another_competency_is_rejected():
    _, reports, rejected = build_report(
        context(), draft(block(competency_id="cmp_db", unconfirmed=[]))
    )
    assert reports[1].confirmed == []
    assert rejected == ["cmp_db confirmed 1: finding belongs to another competency"]


def test_a_finding_is_cited_once_per_competency():
    _, reports, rejected = build_report(
        context(),
        draft(
            block(confirmed=[sentence(), sentence(text="다른 문장")], unconfirmed=[])
        ),
    )
    assert len(reports[0].confirmed) == 1
    assert rejected == ["cmp_api confirmed 2: duplicate finding"]


def test_unknown_and_duplicate_competency_blocks_are_rejected():
    _, reports, rejected = build_report(
        context(), draft(block(competency_id="cmp_nope"), block(), block())
    )
    assert rejected == [
        "competency 1: unknown competency",
        "competency 3: duplicate competency",
    ]
    assert len(reports[0].confirmed) == 1


def test_questions_are_trimmed_deduplicated_and_capped():
    questions = ["  같은 질문 ", "같은 질문", "", "가" * 121, "둘", "셋", "넷"]
    _, reports, rejected = build_report(
        context(), draft(block(next_questions=questions))
    )
    assert reports[0].next_questions == ["같은 질문", "둘", "셋"]
    assert rejected == [
        "cmp_api question 2: duplicate question",
        "cmp_api question 3: invalid question length",
        "cmp_api question 4: invalid question length",
        "cmp_api question 7: question limit exceeded",
    ]


def test_a_competency_without_findings_keeps_its_questions():
    # cmp_db has no adopted finding; the next interviewer still gets the
    # questions, only the sentence lists stay empty (#239, 10/29 rule).
    _, reports, rejected = build_report(
        context(),
        draft(
            block(),
            block(
                competency_id="cmp_db",
                confirmed=[],
                unconfirmed=[],
                next_questions=["느린 쿼리를 어떻게 찾았는지 물어본다"],
            ),
        ),
    )
    assert rejected == []
    db = reports[1]
    assert db.sentence_count == 0
    assert db.next_questions == ["느린 쿼리를 어떻게 찾았는지 물어본다"]


def test_sentence_limit_per_list():
    items = [sentence(finding_id=f"fnd_{i}") for i in range(5)]
    findings = [
        {
            "findingId": f"fnd_{i}",
            "competencyId": "cmp_api",
            "findingType": "COMPETENCY_EVIDENCE",
            "text": "근거",
        }
        for i in range(5)
    ]
    _, reports, rejected = build_report(
        context(findings=findings), draft(block(confirmed=items, unconfirmed=[]))
    )
    assert len(reports[0].confirmed) == 4
    assert rejected == ["cmp_api confirmed 5: sentence limit exceeded"]


def test_overview_too_long_is_dropped_not_truncated():
    overview, _, rejected = build_report(context(), draft(overview="가" * 601))
    assert overview == ""
    assert rejected == ["overview: too long"]


async def test_agent_completed_partial_and_empty():
    good = await ReportAgent(FakeReportGenerator(draft()), model="fake").run(context())
    assert good.status == "completed"
    assert good.sentence_count == 2
    assert good.model == "fake"
    assert good.elapsed_ms >= 0

    partial = await ReportAgent(
        FakeReportGenerator(
            draft(block(confirmed=[sentence(), sentence(finding_id="x")]))
        )
    ).run(context())
    assert partial.status == "partial"
    assert partial.rejections == ["cmp_api confirmed 2: finding not adopted"]

    empty = await ReportAgent(
        FakeReportGenerator(draft(block(confirmed=[], unconfirmed=[])))
    ).run(context())
    assert empty.status == "empty"
    assert empty.error is None
    assert [c.competency_id for c in empty.competencies] == ["cmp_api", "cmp_db"]


async def test_agent_does_not_call_the_model_without_findings_or_competencies():
    generator = FakeReportGenerator(draft())
    no_findings = await ReportAgent(generator).run(context(findings=[]))
    assert no_findings.status == "empty"
    assert no_findings.warnings == ["NO_ADOPTED_FINDINGS"]
    no_competencies = await ReportAgent(generator).run(context(competencies=[]))
    assert no_competencies.status == "empty"
    assert no_competencies.warnings == ["NO_COMPETENCIES"]
    assert generator.calls == 0


async def test_agent_rejects_duplicate_context_ids():
    doubled = context().findings + context().findings[:1]
    result = await ReportAgent(FakeReportGenerator(draft())).run(
        context(findings=[f.model_dump(by_alias=True) for f in doubled])
    )
    assert result.status == "failed"
    assert result.error.code == "DUPLICATE_CONTEXT_IDS"


async def test_agent_maps_timeouts_and_provider_errors():
    class Slow:
        async def generate(self, context):
            await asyncio.sleep(1)
            return draft()

    class Broken:
        def __init__(self, code, retryable):
            self.code, self.retryable = code, retryable

        async def generate(self, context):
            raise ReportError(self.code, retryable=self.retryable)

    slow = await ReportAgent(Slow(), timeout_seconds=0.01).run(context())
    assert slow.status == "failed"
    assert (slow.error.code, slow.error.retryable) == ("LLM_TIMEOUT", True)

    busy = await ReportAgent(Broken("LLM_RATE_LIMITED", True)).run(context())
    assert (busy.error.code, busy.error.retryable) == ("LLM_RATE_LIMITED", True)
    bad = await ReportAgent(Broken("LLM_BAD_REQUEST", False)).run(context())
    assert (bad.error.code, bad.error.retryable) == ("LLM_BAD_REQUEST", False)


async def test_extractive_baseline_files_each_finding_by_type():
    result = await ReportAgent(ExtractiveReportGenerator(), model="extractive").run(
        context()
    )
    assert result.status == "completed"
    assert result.overview == "캐시와 결제를 이야기한 면접."
    api, db = result.competencies
    assert [s.finding_id for s in api.confirmed] == ["fnd_cache"]
    assert [s.finding_id for s in api.unconfirmed] == ["fnd_idem"]
    assert api.next_questions == []
    # A finding without a competency has no block to go in.
    assert db.sentence_count == 0


def test_payload_carries_sentences_ids_and_requested_at_only():
    result = ReportResult.model_validate(
        {
            "interviewId": "int_test",
            "status": "completed",
            "overview": "요약",
            "competencies": [
                {
                    "competencyId": "cmp_api",
                    "confirmed": [{"text": "문장", "findingId": "fnd_cache"}],
                    "unconfirmed": [],
                    "nextQuestions": ["질문"],
                }
            ],
            "model": "fake",
            "rejections": ["cmp_api confirmed 2: finding not adopted"],
        }
    )
    body = report_payload(result, requested_at="2026-10-31T09:11:40Z").model_dump(
        by_alias=True
    )
    assert body == {
        "status": "completed",
        "requestedAt": "2026-10-31T09:11:40Z",
        "overview": "요약",
        "competencies": [
            {
                "competencyId": "cmp_api",
                "confirmed": [{"text": "문장", "findingId": "fnd_cache"}],
                "unconfirmed": [],
                "nextQuestions": ["질문"],
            }
        ],
        "model": "fake",
    }
    failed = report_payload(
        result.model_copy(update={"status": "failed"}), requested_at="t"
    )
    assert failed.overview == "" and failed.competencies == []
    assert failed.model == "fake"
