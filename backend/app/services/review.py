"""검토 화면의 계산 규칙 (#137 1-2 · #163).

coverage · 문답의 역량 · findings 조인 · 목록 집계를 한 곳에서 한다.

입력은 저장된 JSON 그대로다. 면접 전 분석(`interview_prep`)의 역량 · 주장, 요약
(`session_summary`)의 moments · findings(AI 모양, camelCase), 면접관의 표시
(`review_mark`). 저장소를 모른다 — 상세와 목록이 같은 함수를 불러 숫자가 어긋나지
않게 한다.

조인이 실패해도 터지지 않는다. 면접 전 분석이 다시 돌아 역량 · 주장 id 가 바뀌면 그
항목의 역량 이름과 지원서 문장이 비어 나올 뿐이다.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from app.domain.models import (
    CoverageState,
    FindingState,
    FindingType,
    InterviewPrep,
    ReviewMark,
    SessionSummary,
)

JsonList = list[dict[str, Any]]

#: 표시 대상의 종류. 문답(moment)은 북마크, 검토 항목(finding)은 채택을 받는다.
ItemKind = Literal["moment", "finding"]

_CONFIRMING = frozenset({FindingType.CLAIM_VERIFIED, FindingType.COMPETENCY_EVIDENCE})


@dataclass(frozen=True)
class Review:
    """상세의 계산된 부분. 모양은 #137 1-2 응답 그대로다."""

    coverage: JsonList
    moments: JsonList
    findings: JsonList

    def counts(self) -> dict[str, int]:
        """목록 한 줄의 집계 (#137 1-1). 반려한 항목은 검토할 것에서 빠진다."""
        states = [f["state"] for f in self.findings]
        return {
            "coverageConfirmed": sum(
                c["state"] == CoverageState.CONFIRMED for c in self.coverage
            ),
            "coverageTotal": len(self.coverage),
            "findings": len(self.findings),
            "needsReview": states.count(FindingState.PROPOSED.value),
            "adopted": states.count(FindingState.ADOPTED.value),
        }


def build_review(
    prep: InterviewPrep | None, summary: SessionSummary, marks: Iterable[ReviewMark]
) -> Review:
    """면접 전 분석 · 요약 · 표시를 상세의 계산된 부분으로.

    요약이 READY 가 아니면 moments · findings 가 비어 있다(FAILED 로 갈 때 비운다).
    그때도 coverage 는 면접 전 분석의 역량 전부를 MISSING 으로 보인다.
    """
    competencies = [] if prep is None else prep.competencies
    claims = [] if prep is None else prep.resume_claims
    moments, findings = summary.moments, summary.findings
    names = {c["competencyId"]: c["name"] for c in competencies}
    claim_by_id = {c["claimId"]: c for c in claims}
    mark_by_id = {m.item_id: m for m in marks}

    return Review(
        coverage=[
            {"name": c["name"], "state": _coverage(c["competencyId"], findings)}
            for c in competencies
        ],
        moments=[
            {
                "id": m["momentId"],
                "atSec": m["atMs"] / 1000,
                "label": m["label"],
                "question": m["question"],
                "answer": m["answer"],
                "competencies": _competencies_in(m, findings, names),
                "bookmarked": m["momentId"] in mark_by_id
                and mark_by_id[m["momentId"]].bookmarked,
            }
            for m in moments
        ],
        findings=[
            {
                "id": f["findingId"],
                "type": f["type"],
                "competency": names.get(f.get("competencyId") or ""),
                **_source(f, claim_by_id),
                "transcript": f.get("evidenceQuote"),
                "rationale": f["summary"],
                "atSec": None
                if f.get("evidenceTMs") is None
                else f["evidenceTMs"] / 1000,
                # 표시가 없으면 「제안됨」이다.
                "state": mark_by_id[f["findingId"]].state
                if f["findingId"] in mark_by_id
                else FindingState.PROPOSED,
            }
            for f in findings
        ],
    )


def _coverage(competency_id: str, findings: JsonList) -> CoverageState:
    """역량 하나의 상태 (#137 1-2 「coverage 규칙」). 모순이 근거를 덮는다."""
    types = {f["type"] for f in findings if f.get("competencyId") == competency_id}
    if FindingType.CLAIM_CONTRADICTED in types:
        return CoverageState.PARTIAL
    if types & _CONFIRMING:
        return CoverageState.CONFIRMED
    if FindingType.CLAIM_UNVERIFIED in types:
        return CoverageState.PARTIAL
    return CoverageState.MISSING


def _competencies_in(
    moment: dict[str, Any], findings: JsonList, names: dict[str, str]
) -> list[str]:
    """근거 시각이 그 문답 구간 `[atMs, endMs]` 안에 드는 findings 의 역량, 한 번씩."""
    found: list[str] = []
    for f in findings:
        at = f.get("evidenceTMs")
        name = names.get(f.get("competencyId") or "")
        if (
            at is not None
            and name is not None
            and moment["atMs"] <= at <= moment["endMs"]
            and name not in found
        ):
            found.append(name)
    return found


def _source(finding: dict[str, Any], claims: dict[str, Any]) -> dict[str, Any]:
    """지원서 주장에 걸린 항목은 그 문장과 단락, 답변만으로 된 항목은 「면접 답변」."""
    claim_id = finding.get("claimId")
    if claim_id:
        claim = claims.get(claim_id) or {}
        section = claim.get("section")
        return {
            "source": f"지원서 · {section}" if section else "지원서",
            "quote": claim.get("quote"),
        }
    if finding["type"] == FindingType.GAP:
        return {"source": None, "quote": None}
    return {"source": "면접 답변", "quote": None}


def item_kinds(summary: SessionSummary) -> dict[str, ItemKind]:
    """상세에 나오는 표시 대상 id 와 그 종류. 문답은 북마크, 검토 항목은 채택이다."""
    kinds: dict[str, ItemKind] = {m["momentId"]: "moment" for m in summary.moments}
    kinds.update((f["findingId"], "finding") for f in summary.findings)
    return kinds
