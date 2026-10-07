"""Synthetic input only; exercise reference, revision and citation failures."""

import asyncio
import json
from pathlib import Path

import pytest

from irya_ai.cli import main
from irya_ai.findings import (
    ExtractiveFindingsGenerator,
    FakeFindingsGenerator,
    FindingsAgent,
    FindingsError,
    build_findings,
    finding_id,
)
from irya_ai.schemas import (
    FindingDraft,
    FindingsDraft,
    InterviewContext,
    TranscriptSnapshot,
    Utterance,
)
from irya_ai.schemas.analysis import FindingState, FindingType

TEXT = "Redis 캐시를 적용해 응답 시간을 60% 줄였습니다."


def context() -> InterviewContext:
    return InterviewContext.model_validate(
        {
            "sessionId": "ses_test",
            "company": {"companyId": "cmp_test", "name": "합성회사"},
            "candidate": {
                "candidateId": "cnd_test",
                "name": "이름을 모델에 보내지 않음",
            },
            "jobDescription": {
                "jdId": "jd_test",
                "companyId": "cmp_test",
                "title": "백엔드",
                "description": "서버 개발",
            },
            "competencies": [
                {"competencyId": "cpt_test", "jdId": "jd_test", "name": "성능 개선"}
            ],
            "resume": {
                "resumeId": "rsm_test",
                "candidateId": "cnd_test",
                "storageKey": "private-storage-key",
                "text": "본문을 모델에 보내지 않음",
            },
            "resumeClaims": [
                {"claimId": "clm_test", "resumeId": "rsm_test", "quote": TEXT}
            ],
        }
    )


def utterance(**changes) -> Utterance:
    return Utterance.model_validate(
        {
            "utterance_id": "utt_test",
            "session_id": "ses_test",
            "track_id": "TR_test",
            "speaker": "CANDIDATE",
            "seq": 5,
            "start_ms": 1000,
            "end_ms": 4000,
            "content": TEXT,
            **changes,
        }
    )


def draft(**changes) -> FindingDraft:
    return FindingDraft.model_validate(
        {
            "type": "COMPETENCY_EVIDENCE",
            "competency_id": "cpt_test",
            "claim_id": None,
            "evidence_utterance_id": "utt_test",
            "evidence_quote": TEXT,
            "summary": "응답 시간 개선 경험을 설명했습니다.",
            **changes,
        }
    )


def bundle(*items: FindingDraft) -> FindingsDraft:
    return FindingsDraft(findings=list(items))


@pytest.mark.parametrize("kind", list(FindingType))
def test_verified_items_use_existing_refs_and_code_owned_fields(kind):
    changes = {"type": kind}
    if kind.value.startswith("CLAIM_"):
        changes["claim_id"] = "clm_test"
    elif kind is FindingType.GAP:
        changes.update(evidence_utterance_id=None, evidence_quote=None)
    items, rejected = build_findings(context(), [utterance()], bundle(draft(**changes)))
    assert rejected == []
    assert len(items) == 1
    assert items[0].state is FindingState.PROPOSED
    assert items[0].evidence_t_ms == (None if kind is FindingType.GAP else 1000)
    assert items[0].session_id == "ses_test"


@pytest.mark.parametrize(
    "changes",
    [
        {"competency_id": "missing"},
        {"claim_id": "missing"},
        {"type": "CLAIM_VERIFIED"},
        {"competency_id": None},
        {"claim_id": "clm_test"},
        {"evidence_utterance_id": "missing"},
        {"evidence_quote": None},
        {"evidence_quote": "redis 캐시"},
        {"evidence_quote": "Redis캐시를 적용해"},
        {"summary": ""},
        {"summary": "가" * 241},
        {"summary": "응답 시간을 99% 개선했습니다."},
        {"type": "GAP"},
    ],
)
def test_bad_drafts_are_rejected_without_echoing_input(changes):
    items, rejected = build_findings(context(), [utterance()], bundle(draft(**changes)))
    assert items == []
    assert len(rejected) == 1
    assert rejected[0].startswith("finding 1: ")
    assert TEXT not in rejected[0]
    assert "missing" not in rejected[0]
    assert "99%" not in rejected[0]


@pytest.mark.parametrize(
    "changes", [{"speaker": "INTERVIEWER"}, {"pass_type": "INTERIM"}]
)
def test_questions_and_interims_cannot_be_claim_evidence(changes):
    items, rejected = build_findings(context(), [utterance(**changes)], bundle(draft()))
    assert items == []
    assert rejected == ["finding 1: evidence requires a candidate FINAL utterance"]


def test_quote_in_another_utterance_cannot_pass():
    finals = [
        utterance(content="캐시 설명은 다른 답변에 있습니다."),
        utterance(utterance_id="utt_other", seq=6),
    ]
    assert build_findings(context(), finals, bundle(draft()))[0] == []


def test_numbers_from_claim_and_answer_support_contradiction_summary():
    quote = "응답 시간은 30% 단축했습니다."
    item = draft(
        type="CLAIM_CONTRADICTED",
        claim_id="clm_test",
        evidence_quote=quote,
        summary="이력서의 60%와 답변의 30%가 다릅니다.",
    )
    items, rejected = build_findings(
        context(), [utterance(content=quote)], bundle(item)
    )
    assert len(items) == 1
    assert rejected == []


def test_id_is_stable_across_order_summary_wording_and_normalized_quote():
    original = draft()
    changed = draft(
        summary="다른 중립적 문구", evidence_quote=TEXT.replace(" ", "\n  ", 1)
    )
    assert finding_id(original) == finding_id(changed)
    assert finding_id(original) != finding_id(draft(evidence_quote="다른 인용"))
    gap = draft(type="GAP", evidence_utterance_id=None, evidence_quote=None)
    first = build_findings(context(), [utterance()], bundle(original, gap))[0]
    second = build_findings(context(), [utterance()], bundle(gap, original))[0]
    assert [x.finding_id for x in first] == [x.finding_id for x in second]


def test_duplicates_and_limit_are_visible():
    gap = draft(type="GAP", evidence_utterance_id=None, evidence_quote=None)
    items, rejected = build_findings(
        context(), [utterance()], bundle(draft(), draft(), gap), max_findings=1
    )
    assert len(items) == 1
    assert rejected == [
        "finding 2: duplicate finding",
        "finding 3: finding limit exceeded",
    ]


async def test_last_final_wins_and_later_interim_does_not_overwrite():
    old = utterance(content="이전 답변입니다.")
    final = utterance()
    interim = utterance(content="나중에 도착한 임시 전사입니다.", pass_type="INTERIM")
    generator = FakeFindingsGenerator(bundle(draft()))
    result = await FindingsAgent(generator).run(
        context(),
        TranscriptSnapshot(session_id="ses_test", utterances=[old, final, interim]),
    )
    assert result.status == "completed"
    assert result.findings[0].evidence_quote == TEXT
    rejected = await FindingsAgent(
        FakeFindingsGenerator(bundle(draft(evidence_quote=old.content)))
    ).run(context(), TranscriptSnapshot(session_id="ses_test", utterances=[old, final]))
    assert rejected.status == "failed"
    assert rejected.error.code == "NO_GROUNDED_FINDINGS"


async def test_session_mismatch_never_calls_model():
    generator = FakeFindingsGenerator(bundle(draft()))
    result = await FindingsAgent(generator).run(
        context(), TranscriptSnapshot(session_id="other")
    )
    assert result.error.code == "CONTEXT_SESSION_MISMATCH"
    assert generator.calls == 0


async def test_duplicate_context_ids_fail_before_model():
    ctx = context()
    ctx.competencies.append(ctx.competencies[0])
    generator = FakeFindingsGenerator(bundle(draft()))
    result = await FindingsAgent(generator).run(
        ctx, TranscriptSnapshot(session_id="ses_test", utterances=[utterance()])
    )
    assert result.error.code == "DUPLICATE_CONTEXT_IDS"
    assert generator.calls == 0


@pytest.mark.parametrize("case", ["no_prep", "no_finals"])
async def test_empty_input_skips_model(case):
    ctx = context()
    if case == "no_prep":
        ctx.competencies = []
        ctx.resume_claims = []
    generator = FakeFindingsGenerator(bundle(draft()))
    snapshot = TranscriptSnapshot(
        session_id="ses_test", utterances=[] if case == "no_finals" else [utterance()]
    )
    result = await FindingsAgent(generator).run(ctx, snapshot)
    assert result.status == "empty"
    assert generator.calls == 0


async def test_partial_is_not_failed_and_errors_are_structured():
    result = await FindingsAgent(
        FakeFindingsGenerator(bundle(draft(), draft(competency_id="missing")))
    ).run(
        context(), TranscriptSnapshot(session_id="ses_test", utterances=[utterance()])
    )
    assert result.status == "partial"
    assert len(result.findings) == 1
    assert result.error is None


@pytest.mark.parametrize("case", ["error", "timeout", "cancel"])
async def test_failures_and_cancellation(case):
    class Generator:
        async def generate(self, ctx, finals):
            if case == "error":
                raise FindingsError("LLM_RATE_LIMITED", retryable=True)
            if case == "cancel":
                raise asyncio.CancelledError
            await asyncio.sleep(2)

    agent = FindingsAgent(Generator(), timeout_seconds=0.01)
    if case == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await agent.run(
                context(),
                TranscriptSnapshot(session_id="ses_test", utterances=[utterance()]),
            )
    else:
        result = await agent.run(
            context(),
            TranscriptSnapshot(session_id="ses_test", utterances=[utterance()]),
        )
        assert result.status == "failed"
        assert result.error.retryable


async def test_offline_baseline_only_reports_exact_claim_mentions():
    agent = FindingsAgent(ExtractiveFindingsGenerator())
    result = await agent.run(
        context(), TranscriptSnapshot(session_id="ses_test", utterances=[utterance()])
    )
    assert [f.type for f in result.findings] == [FindingType.CLAIM_VERIFIED]
    assert result.findings[0].claim_id == "clm_test"
    empty = await agent.run(
        context(),
        TranscriptSnapshot(
            session_id="ses_test",
            utterances=[utterance(content="다른 프로젝트를 설명했습니다.")],
        ),
    )
    assert empty.status == "completed"
    assert empty.findings == []


@pytest.mark.parametrize("separate", [True, False])
def test_cli_reads_persisted_context_and_finals(tmp_path: Path, capsys, separate):
    payload = context().model_dump(by_alias=True)
    snapshot = TranscriptSnapshot(session_id="ses_test", utterances=[utterance()])
    args = ["findings", str(tmp_path / "context.json")]
    if separate:
        (tmp_path / "snapshot.json").write_text(snapshot.model_dump_json(by_alias=True))
        args.append(str(tmp_path / "snapshot.json"))
    else:
        payload["utterances"] = snapshot.model_dump(by_alias=True)["utterances"]
    (tmp_path / "context.json").write_text(json.dumps(payload))
    assert main([*args, "--backend", "extractive"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["status"] == "completed"
    assert body["findings"][0]["claimId"] == "clm_test"
    assert body["findings"][0]["state"] == "PROPOSED"


def test_cli_invalid_input_does_not_echo_sensitive_content(tmp_path, capsys):
    p = tmp_path / "context.json"
    p.write_text('{"secret": "private-resume-body"}')
    assert main(["findings", str(p), "--backend", "extractive"]) == 2
    output = capsys.readouterr().out
    assert "INVALID_FINDINGS_INPUT" in output
    assert "private-resume-body" not in output


def test_citation_time_comes_from_the_cited_word_not_the_model():
    source = utterance(
        words=[
            {"seq": 0, "start_ms": 1000, "end_ms": 1200, "content": "Redis"},
            {"seq": 1, "start_ms": 2000, "end_ms": 2300, "content": "응답"},
        ]
    )
    items, rejected = build_findings(
        context(), [source], bundle(draft(evidence_quote="응답 시간을 60%"))
    )
    assert rejected == []
    assert items[0].evidence_t_ms == 2000


@pytest.mark.parametrize("kwargs", [{"timeout_seconds": 0}, {"max_findings": 0}])
def test_invalid_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        FindingsAgent(FakeFindingsGenerator(bundle()), **kwargs)


def test_new_sample_uses_the_prep_and_stored_transcript_contract():
    sample = Path(__file__).parents[1] / "data/samples/findings_context.json"
    payload = json.loads(sample.read_text())
    finals = payload.pop("utterances")
    ctx = InterviewContext.model_validate(payload)
    snapshot = TranscriptSnapshot(session_id=ctx.session_id, utterances=finals)
    result = asyncio.run(
        FindingsAgent(ExtractiveFindingsGenerator()).run(ctx, snapshot)
    )
    assert result.status == "completed"
    assert len(result.findings) == 1
    assert result.findings[0].claim_id == ctx.resume_claims[0].claim_id
