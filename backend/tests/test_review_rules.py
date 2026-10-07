"""검토 화면의 계산 규칙 (#137 1-2 · #163) — 상세와 목록이 같이 쓴다.

골든 테스트 하나가 규칙 대부분을 고정한다. 입력은 데모 시드의 김도현(#137 1-2 예시)이고,
기대값은 #137 1-2 응답을 그대로 옮긴 것이다 — 「위 예시는 이 규칙을 그대로 적용한
결과입니다」. 예시가 덮지 않는 갈래만 따로 본다.
"""

from typing import Any

from app.domain.models import FindingState, ReviewMark
from app.services.review import build_review
from tests.conftest import DEMO

COMPETENCIES = DEMO["prep"]["competencies"]
CLAIMS = DEMO["prep"]["resumeClaims"]
MOMENTS = DEMO["review"]["moments"]
FINDINGS = DEMO["review"]["findings"]


def kim_marks() -> list[ReviewMark]:
    [kim] = [c for c in DEMO["candidates"] if c["key"] == "kim"]
    return [
        ReviewMark(session_id="ses_demo", item_id=m["itemId"], **_mark_fields(m))
        for m in kim["marks"]
    ]


def _mark_fields(mark: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if "state" in mark:
        fields["state"] = FindingState(mark["state"])
    if "bookmarked" in mark:
        fields["bookmarked"] = mark["bookmarked"]
    return fields


def test_the_137_example_comes_out_as_written() -> None:
    review = build_review(COMPETENCIES, CLAIMS, MOMENTS, FINDINGS, kim_marks())

    assert review.coverage == [
        {"name": "서비스 설계", "state": "CONFIRMED"},
        {"name": "성능 개선", "state": "PARTIAL"},
        # 근거가 있어도 모순을 덮지 않는다.
        {"name": "협업", "state": "PARTIAL"},
        {"name": "장애 대응", "state": "MISSING"},
    ]
    assert review.moments == [
        {
            "id": "mom_qa_utt_TR_a_0001",
            "atSec": 15.0,
            "label": "자기소개",
            "question": "간단히 자기소개 부탁드립니다.",
            "answer": "실시간 스트리밍 파이프라인을 주로 맡아 왔다고 소개했습니다.",
            "competencies": ["서비스 설계"],
            "bookmarked": False,
        },
        {
            "id": "mom_qa_utt_TR_a_0007",
            "atSec": 118.0,
            "label": "개인 기여",
            "question": "그 프로젝트에서 본인이 직접 맡은 부분은 어디까지인가요?",
            "answer": "배포 파이프라인을 처음부터 구성했다고 답했습니다.",
            # 모순과 근거 둘 다 협업이다 — 한 번만.
            "competencies": ["협업"],
            "bookmarked": True,
        },
        {
            "id": "mom_qa_utt_TR_a_0015",
            "atSec": 262.0,
            "label": "성능 개선",
            "question": "초당 2만 건을 처리할 때 병목은 어디였나요?",
            "answer": "병목은 구체적으로 재보지 못했다고 답했습니다.",
            "competencies": ["성능 개선"],
            "bookmarked": True,
        },
        {
            "id": "mom_qa_utt_TR_a_0024",
            "atSec": 405.0,
            "label": "장애 대응",
            "question": "최근에 대응한 장애와 복구 과정을 설명해 주세요.",
            "answer": (
                "재처리 큐를 사용했다고 했지만 원인과 재발 방지는 말하지 않았습니다."
            ),
            # GAP 은 근거 시각이 없어 어느 문답에도 붙지 않는다.
            "competencies": [],
            "bookmarked": False,
        },
    ]
    assert review.findings == [
        {
            "id": "fnd_CLAIM_CONTRADICTED_clm_001_utt_TR_b_0008",
            "type": "CLAIM_CONTRADICTED",
            "competency": "협업",
            "source": "지원서 · 프로젝트 1",
            "quote": "팀 프로젝트에서 API와 프론트 화면을 함께 맡았습니다.",
            "transcript": "배포 파이프라인은 제가 처음부터 구성했습니다.",
            "rationale": (
                "지원서의 담당 범위(API · 프론트)와 "
                "면접에서 말한 범위(배포 파이프라인)가 다릅니다."
            ),
            "atSec": 121.4,
            "state": "PROPOSED",
        },
        {
            "id": "fnd_CLAIM_UNVERIFIED_clm_002_utt_TR_b_0016",
            "type": "CLAIM_UNVERIFIED",
            "competency": "성능 개선",
            "source": "지원서 · 성과 2",
            "quote": "초당 2만 건의 이벤트를 안정적으로 처리했습니다.",
            "transcript": (
                "초당 2만 건까지 올렸는데 병목은 구체적으로 재보지 못했습니다."
            ),
            "rationale": "측정 환경과 병목 확인 과정이 답변에서 드러나지 않았습니다.",
            "atSec": 268.9,
            "state": "PROPOSED",
        },
        {
            "id": "fnd_COMPETENCY_EVIDENCE_cpt_design_utt_TR_b_0002",
            "type": "COMPETENCY_EVIDENCE",
            "competency": "서비스 설계",
            "source": "면접 답변",
            "quote": None,
            "transcript": "실시간 스트리밍 파이프라인을 주로 맡아 왔습니다.",
            "rationale": "맡아 온 시스템의 범위를 직접 설명했습니다.",
            "atSec": 19.2,
            "state": "PROPOSED",
        },
        {
            "id": "fnd_COMPETENCY_EVIDENCE_cpt_collab_utt_TR_b_0009",
            "type": "COMPETENCY_EVIDENCE",
            "competency": "협업",
            "source": "면접 답변",
            "quote": None,
            "transcript": "팀에서 함께 설계했고 주요 기능은 제가 구현했습니다.",
            "rationale": "팀 작업과 본인 구현을 나눠 말했습니다.",
            "atSec": 130.5,
            "state": "PROPOSED",
        },
        {
            "id": "fnd_GAP_cpt_incident",
            "type": "GAP",
            "competency": "장애 대응",
            "source": None,
            "quote": None,
            "transcript": None,
            "rationale": "장애 원인과 재발 방지에 대한 발언이 없습니다.",
            "atSec": None,
            "state": "PROPOSED",
        },
    ]
    # #137 1-1 의 목록 예시와 같은 숫자다.
    assert review.counts() == {
        "coverageConfirmed": 1,
        "coverageTotal": 4,
        "findings": 5,
        "needsReview": 5,
        "adopted": 0,
    }


def test_the_interviewers_marks_show_and_count() -> None:
    marks = [
        ReviewMark("ses_demo", FINDINGS[0]["findingId"], state=FindingState.ADOPTED),
        ReviewMark("ses_demo", FINDINGS[1]["findingId"], state=FindingState.REJECTED),
        # 재분석으로 사라진 id 의 표시는 어디에도 나오지 않는다.
        ReviewMark("ses_demo", "fnd_gone", state=FindingState.ADOPTED),
    ]

    review = build_review(COMPETENCIES, CLAIMS, MOMENTS, FINDINGS, marks)

    assert [f["state"] for f in review.findings[:2]] == ["ADOPTED", "REJECTED"]
    counts = review.counts()
    # 반려한 것은 검토할 것에서 빠진다.
    assert (counts["needsReview"], counts["adopted"], counts["findings"]) == (3, 1, 5)


def test_no_analysis_means_every_competency_is_missing() -> None:
    """요약이 FAILED 인 면접(#163 결정) — 분석은 비어도 역량은 보인다."""
    review = build_review(COMPETENCIES, CLAIMS, [], [], [])

    assert [c["state"] for c in review.coverage] == ["MISSING"] * 4
    assert (review.moments, review.findings) == ([], [])


def test_a_verified_claim_confirms_its_competency() -> None:
    verified = FINDINGS[1] | {"type": "CLAIM_VERIFIED"}

    review = build_review(COMPETENCIES, CLAIMS, [], [verified], [])

    assert review.coverage[1] == {"name": "성능 개선", "state": "CONFIRMED"}


def test_ids_the_prep_no_longer_has_do_not_break_the_join() -> None:
    """면접 전 분석이 다시 돌아 역량 · 주장 id 가 바뀐 경우. 500 이 아니라 빈 값이다."""
    review = build_review([], [], MOMENTS, FINDINGS[:1], [])

    [finding] = review.findings
    assert (finding["competency"], finding["source"], finding["quote"]) == (
        None,
        "지원서",
        None,
    )
    assert review.moments[1]["competencies"] == []


def test_a_claim_without_a_section_is_just_the_resume() -> None:
    claims = [CLAIMS[0] | {"section": None}]

    review = build_review(COMPETENCIES, claims, [], FINDINGS[:1], [])

    assert review.findings[0]["source"] == "지원서"


def test_evidence_on_the_edge_of_a_moment_belongs_to_it() -> None:
    """구간은 양 끝을 포함한다 — 질문 시작과 답변 끝에 걸친 근거도 그 문답이다."""
    first, last = MOMENTS[0], MOMENTS[1]
    on_edges = [
        FINDINGS[2] | {"evidenceTMs": first["atMs"]},
        FINDINGS[3] | {"evidenceTMs": last["endMs"]},
    ]

    review = build_review(COMPETENCIES, CLAIMS, MOMENTS, on_edges, [])

    assert review.moments[0]["competencies"] == ["서비스 설계"]
    assert review.moments[1]["competencies"] == ["협업"]
