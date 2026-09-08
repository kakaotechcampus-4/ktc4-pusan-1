import pytest
from pydantic import ValidationError

from irya_ai.schemas import (
    Finding,
    FindingType,
    InterviewContext,
    PassType,
    SpeakerRole,
    Utterance,
)


def _utterance(**overrides) -> Utterance:
    base = {
        "utterance_id": "utt_001",
        "session_id": "ses_123",
        "track_id": "trk_candidate",
        "speaker": SpeakerRole.CANDIDATE,
        "seq": 1,
        "start_ms": 1000,
        "end_ms": 2500,
        "content": "조회가 많은 상품 API 앞에 Redis를 뒀습니다.",
    }
    return Utterance(**{**base, **overrides})


def test_utterance_accepts_snake_case_and_camel_case() -> None:
    from_snake = _utterance()
    from_camel = Utterance.model_validate(
        {
            "utteranceId": "utt_001",
            "sessionId": "ses_123",
            "trackId": "trk_candidate",
            "speaker": "CANDIDATE",
            "seq": 1,
            "startMs": 1000,
            "endMs": 2500,
            "content": "조회가 많은 상품 API 앞에 Redis를 뒀습니다.",
        }
    )

    assert from_snake == from_camel


def test_utterance_dumps_camel_case_for_api() -> None:
    dumped = _utterance().model_dump(by_alias=True)

    assert dumped["utteranceId"] == "utt_001"
    assert dumped["startMs"] == 1000
    assert dumped["passType"] == "FINAL"
    assert "start_ms" not in dumped


def test_utterance_rejects_reversed_time_range() -> None:
    with pytest.raises(ValidationError, match="end_ms must be >= start_ms"):
        _utterance(start_ms=3000, end_ms=2000)


def test_utterance_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _utterance(unexpected="value")


def test_utterance_helpers() -> None:
    interim = _utterance(pass_type=PassType.INTERIM)

    assert _utterance().is_final
    assert not interim.is_final
    assert _utterance().duration_ms == 1500


def test_finding_requires_evidence_unless_gap() -> None:
    with pytest.raises(ValidationError, match="requires evidence"):
        Finding(
            finding_id="fnd_001",
            session_id="ses_123",
            type=FindingType.COMPETENCY_EVIDENCE,
            summary="근거 없는 항목",
        )

    gap = Finding(
        finding_id="fnd_002",
        session_id="ses_123",
        type=FindingType.GAP,
        competency_id="cpt_learning",
        summary="학습 태도에 대한 언급이 없었다.",
    )
    assert gap.evidence_quote is None


def test_finding_quote_and_source_must_be_set_together() -> None:
    with pytest.raises(ValidationError, match="set together"):
        Finding(
            finding_id="fnd_003",
            session_id="ses_123",
            type=FindingType.CLAIM_VERIFIED,
            evidence_quote="Redis를 뒀습니다",
            summary="인용만 있고 출처가 없다.",
        )


def test_interview_context_lookups() -> None:
    context = InterviewContext.model_validate(
        {
            "sessionId": "ses_123",
            "company": {"companyId": "cmp_1", "name": "누리뱅크"},
            "jobDescription": {
                "jdId": "jd_1",
                "companyId": "cmp_1",
                "title": "백엔드 신입",
                "description": "API 개발",
            },
            "competencies": [{"competencyId": "cpt_a", "jdId": "jd_1", "name": "협업"}],
            "candidate": {"candidateId": "cnd_1", "name": "정민호"},
            "resumeClaims": [
                {"claimId": "clm_1", "resumeId": "rsm_1", "quote": "Redis 도입"}
            ],
        }
    )

    assert context.competency_by_id("cpt_a").name == "협업"
    assert context.competency_by_id("missing") is None
    assert context.claim_by_id("clm_1").quote == "Redis 도입"
    assert context.claim_by_id("missing") is None
