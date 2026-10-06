"""데모 시드 (#137 6장 · #163) — AI 분석이 붙기 전에도 검토 화면을 끝까지 그리게.

    docker compose exec backend python -m app.seed_demo --owner usr_xxx

FE 목(`demoReview.ts`)의 지원자 5명을 그 사용자 소유의 끝난 면접으로 넣는다. 분석
내용은 #137 1-2 예시 한 벌(`demo_review.json`)을 함께 쓴다 — 계산 규칙 테스트가
읽는 파일과 같다. **데모 계정으로 먼저 한 번 로그인해** `app_user` 를 만든 뒤 쓴다.

다시 돌려도 중복되지 않는다. 이미 있는 데모 면접은 건너뛴다 — 내용을 바꿔 다시
넣지는 않는다. 바꾸려면 그 면접을 지우고 다시 돌린다(세션 · 요약 · 표시는 같이
지워진다).

`app/` 아래에 두는 것은 이미지에 들어가야 해서다. `scripts/` · `tests/` 는 이미지에
복사되지 않는다.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.domain.models import (
    Context,
    FindingState,
    Interview,
    InterviewPrep,
    ReviewMark,
    ReviewStatus,
    Session,
    SessionStatus,
    SessionSummary,
    SummaryStatus,
)
from app.domain.store import Store

DEMO_PATH = Path(__file__).with_name("demo_review.json")

#: 컨텍스트의 직무가 비어 있을 때만 채운다. 데모 계정의 실제 설정을 덮지 않는다.
DEFAULT_ROLE = "백엔드 개발자"


def seed(store: Store, owner_id: str) -> int:
    """데모 면접을 넣고 새로 넣은 건수를 돌려준다. 없는 사용자면 ValueError."""
    if store.get_user(owner_id) is None:
        raise ValueError(
            f"사용자 {owner_id} 가 없습니다. 데모 계정으로 먼저 로그인하세요."
        )
    demo: dict[str, Any] = json.loads(DEMO_PATH.read_text(encoding="utf-8"))

    context = store.ensure_context(Context(owner_id=owner_id))
    if not context.role:
        context.role = DEFAULT_ROLE
        store.save_context(context)

    # 계정마다 따로 넣을 수 있게 id 에 주인을 섞는다.
    suffix = owner_id.removeprefix("usr_")
    added = 0
    for candidate in demo["candidates"]:
        interview_id = f"int_demo_{suffix}_{candidate['key']}"
        if store.get_interview(interview_id) is not None:
            continue
        _add(store, owner_id, interview_id, candidate, demo)
        added += 1
    return added


def _add(
    store: Store,
    owner_id: str,
    interview_id: str,
    candidate: dict[str, Any],
    demo: dict[str, Any],
) -> None:
    began = datetime.fromisoformat(candidate["interviewedAt"])
    ended = began + timedelta(seconds=candidate["durationSec"])
    reviewed_at = candidate["reviewedAt"]
    store.add_interview(
        Interview(
            id=interview_id,
            interviewer_id=owner_id,
            candidate_name=candidate["name"],
            # 목록이 최신순이라 면접 시각을 만든 시각으로 둔다 — FE 목과 같은 순서.
            created_at=began,
            review_status=ReviewStatus(candidate["reviewStatus"]),
            memo=candidate["memo"],
            reviewed_at=None
            if reviewed_at is None
            else datetime.fromisoformat(reviewed_at),
        )
    )
    session = Session(
        id=interview_id.replace("int_", "ses_", 1),
        interview_id=interview_id,
        status=SessionStatus.ENDED,
        created_at=began,
        started_at=began,
        ended_at=ended,
        transcript_origin_at=began,
    )
    store.add_session(session)

    # 면접 전 분석 — 저장소의 정상 경로(열고 → 같은 요청 시각으로 결과)를 그대로 탄다.
    requested = began - timedelta(minutes=10)
    store.ensure_prep(InterviewPrep(interview_id=interview_id, requested_at=requested))
    store.finish_prep(
        InterviewPrep(
            interview_id=interview_id,
            status=SummaryStatus.READY,
            competencies=demo["prep"]["competencies"],
            resume_claims=demo["prep"]["resumeClaims"],
            model="demo",
            requested_at=requested,
            completed_at=requested,
        )
    )

    # 면접 후 분석 — 요약 자리를 연 뒤 결과를 써 넣는다(#164 가 붙기 전의 대역).
    summary = store.ensure_summary(
        SessionSummary(session_id=session.id, requested_at=ended)
    )
    review = demo["review"]
    summary.complete(
        review["summary"],
        review["keyPoints"],
        moments=review["moments"],
        findings=review["findings"],
    )
    store.save_summary(summary)

    for mark in candidate["marks"]:
        store.save_mark(
            ReviewMark(
                session_id=session.id,
                item_id=mark["itemId"],
                state=FindingState(mark.get("state", FindingState.PROPOSED)),
                bookmarked=mark.get("bookmarked", False),
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="검토 화면 데모 데이터를 넣는다.")
    parser.add_argument("--owner", required=True, help="데모 계정의 사용자 id (usr_…)")
    args = parser.parse_args(argv)

    # 인메모리에 넣고 성공한 척 끝나면 서버에는 아무것도 없다.
    if not settings.database_url:
        print("DATABASE_URL 이 비어 있습니다. 시드는 DB 에 넣습니다.", file=sys.stderr)
        return 1

    from app.infra.postgres import PostgresStore

    store = PostgresStore(settings.database_url)
    store.open()
    try:
        store.create_schema()
        added = seed(store, args.owner)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        store.close()
    print(f"데모 면접 {added}건을 넣었습니다 (owner={args.owner}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
