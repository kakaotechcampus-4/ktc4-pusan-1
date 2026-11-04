"""면접 리포트의 계산 규칙 (#238).

리포트는 면접에 없던 사람에게 넘기는 인계 문서다. 점수도 합격 여부도 집계도 없고,
**면접관이 채택한 검토 항목**만 근거로 쓴다.

AI 는 문장과 그 근거의 id 만 보낸다 — `{text, findingId}`. 역량 이름 · 필수 여부 ·
근거의 종류 · 지원서 문장 · 면접 발화 · 시각은 BE 가 붙인다 (#163). 조인은 검토 상세
(`app.services.review`)와 같은 함수를 지나간다 — 같은 근거가 두 화면에서 다르게
보이면 안 된다.

저장소를 모른다. 공개 조회 · AI 입력 · 생성 가능 판정이 모두 여기를 지나가서,
「채택했는데 리포트에 없다」가 생기지 않게 한다.
"""

from collections.abc import Iterable
from typing import Any

from app.domain.models import (
    CoverageState,
    FindingState,
    InterviewPrep,
    ReviewMark,
    SessionSummary,
)
from app.services.review import JsonList, build_review, coverage_state


def adopted_findings(summary: SessionSummary, marks: Iterable[ReviewMark]) -> JsonList:
    """면접관이 채택한 검토 항목. AI 가 보낸 모양 그대로, 저장된 순서다.

    세 곳이 이것을 본다 — 생성 가능 판정(0 개면 409) · AI 입력 · 조회 조인.
    한 곳에서 세지 않으면 「채택했는데 리포트에 없다」가 생긴다.
    """
    picked = {m.item_id for m in marks if m.state == FindingState.ADOPTED}
    return [f for f in summary.findings if f["findingId"] in picked]


def context_competencies(prep: InterviewPrep | None, adopted: JsonList) -> JsonList:
    """AI 입력용 역량 목록. JD 역량 전부와 그 순서, 그리고 그 역량의 상태다.

    상태를 따로 내보내지 않고 역량 한 줄에 붙인다. 생성기는 역량 하나를 읽고 그
    자리의 카드를 만들기 때문에, 두 배열로 나누면 받는 쪽이 id 로 다시 맞춰야
    한다 (#239).

    채택한 근거만 세므로 검토 화면의 coverage 와 다를 수 있다 — 화면은 AI 가 낸
    근거 전부를 보고, 리포트는 면접관이 고른 것만 본다.
    """
    return [
        {
            "competencyId": c["competencyId"],
            "name": c["name"],
            "required": bool(c.get("required", True)),
            "state": coverage_state(c["competencyId"], adopted),
        }
        for c in ([] if prep is None else prep.competencies)
    ]


def build_competencies(
    prep: InterviewPrep | None,
    summary: SessionSummary,
    marks: Iterable[ReviewMark],
    stored: JsonList,
) -> JsonList:
    """AI 가 저장한 리포트 본문에 이름 · 필수 · 상태 · 근거를 붙인다.

    카드는 JD 역량 수만큼, JD 순서로 나간다. AI 가 빠뜨린 역량도 카드로 남아야
    「이번 면접에서 다루지 않음」이 보인다.
    """
    marks = list(marks)
    adopted = adopted_findings(summary, marks)
    picked = {f["findingId"] for f in adopted}
    joined = {
        f["id"]: f
        for f in build_review(prep, summary, marks).findings
        if f["id"] in picked
    }
    written = {c.get("competencyId"): c for c in stored}

    cards: JsonList = []
    for c in [] if prep is None else prep.competencies:
        body = written.get(c["competencyId"]) or {}
        state = coverage_state(c["competencyId"], adopted)
        # MISSING 이면 확인된 점 · 확인되지 않은 점을 비운다. 다루지 않은 역량에
        # 「확인된」 문장이 붙으면 거짓이다. 「다음에 물어볼 것」은 남긴다 —
        # 리포트를 받는 2차 면접관에게는 안 다룬 역량이 바로 물어볼 거리다.
        covered = state is not CoverageState.MISSING
        cards.append(
            {
                "name": c["name"],
                "required": bool(c.get("required", True)),
                "state": state,
                "confirmed": _statements(body.get("confirmed"), joined)
                if covered
                else [],
                "unconfirmed": _statements(body.get("unconfirmed"), joined)
                if covered
                else [],
                "nextQuestions": list(body.get("nextQuestions") or []),
            }
        )
    return cards


def _statements(written: Any, joined: dict[str, dict[str, Any]]) -> JsonList:
    """문장 하나하나에 근거를 붙인다. 채택한 항목을 가리키지 않는 문장은 버린다.

    버리는 쪽을 고른다 — 면접관이 반려한 근거나 사라진 id 를 단 문장이 리포트에
    남으면, 「모든 문장에 근거가 붙는다」가 깨진다.
    """
    out: JsonList = []
    for one in written or []:
        found = joined.get(one.get("findingId") or "")
        if found is None:
            continue
        out.append(
            {
                "text": one.get("text") or "",
                "findingId": found["id"],
                "findingType": found["type"],
                "source": found["source"],
                "quote": found["quote"],
                "transcript": found["transcript"],
                "atSec": found["atSec"],
            }
        )
    return out
