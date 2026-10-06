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
from typing import Any

from app.domain.models import FindingState, ReviewMark

JsonList = list[dict[str, Any]]

_CONFIRMING = frozenset({"CLAIM_VERIFIED", "COMPETENCY_EVIDENCE"})


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
            "coverageConfirmed": sum(c["state"] == "CONFIRMED" for c in self.coverage),
            "coverageTotal": len(self.coverage),
            "findings": len(self.findings),
            "needsReview": states.count(FindingState.PROPOSED.value),
            "adopted": states.count(FindingState.ADOPTED.value),
        }


def build_review(
    competencies: JsonList,
    claims: JsonList,
    moments: JsonList,
    findings: JsonList,
    marks: Iterable[ReviewMark],
) -> Review:
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
                "bookmarked": _mark(mark_by_id, m["momentId"]).bookmarked,
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
                "state": _mark(mark_by_id, f["findingId"]).state.value,
            }
            for f in findings
        ],
    )


def _coverage(competency_id: str, findings: JsonList) -> str:
    """역량 하나의 상태 (#137 1-2 「coverage 규칙」). 모순이 근거를 덮는다."""
    types = {f["type"] for f in findings if f.get("competencyId") == competency_id}
    if "CLAIM_CONTRADICTED" in types:
        return "PARTIAL"
    if types & _CONFIRMING:
        return "CONFIRMED"
    if "CLAIM_UNVERIFIED" in types:
        return "PARTIAL"
    return "MISSING"


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
    if finding["type"] == "GAP":
        return {"source": None, "quote": None}
    return {"source": "면접 답변", "quote": None}


def _mark(marks: dict[str, ReviewMark], item_id: str) -> ReviewMark:
    """표시가 없으면 「제안됨 · 북마크 없음」이다."""
    return marks.get(item_id) or ReviewMark(session_id="", item_id=item_id)
