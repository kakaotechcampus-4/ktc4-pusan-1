"""Agent → BE 최종 리뷰 결과 — `PUT /internal/v1/sessions/{sessionId}/review`.

면접이 끝나면 BE 가 요약 자리를 `PROCESSING` 으로 만들어 두고(`POST
/sessions/{id}/end`), Agent 가 전사를 분석해 그 자리에 결과를 써 넣는다. FE 는
`GET /api/v1/sessions/{sessionId}/summary` 로 그 상태를 읽는다.

**PUT 인 이유는 같은 요청을 여러 번 보내도 결과가 같아야 하기 때문이다.** Agent
쪽 재시도는 HTTP 실패를 못 구분하므로(응답을 못 받은 것인지 처리가 안 된 것인지),
덮어쓰기가 안전한 쪽이 낫다.

**Agent 가 영영 안 부를 수도 있다.** 그 경우를 라우터가 아니라 조회 쪽이 받는다 —
한도를 넘긴 `PROCESSING` 은 읽는 시점에 `FAILED` 가 된다. 여기서 아무것도 안
하는 것이 곧 실패로 수렴하므로, 이 경로가 없어도 화면은 멈추지 않는다.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import StoreDep
from app.api.internal.deps import require_internal_auth
from app.api.internal.schemas import ReviewUpsert
from app.core.errors import ApiError, ErrorCode
from app.domain.models import SessionSummary

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_internal_auth)])

SessionIdPath = Annotated[str, Path(alias="sessionId")]

#: 화면에 보여 줄 게 있는 상태. `partial` 은 요약이 나왔는데 근거 검증에서 일부가
#: 떨어진 경우라(`rejected_point_count`), 보여 줄 내용이 있다.
SHOWABLE = frozenset({"completed", "partial"})


@router.put(
    "/sessions/{sessionId}/review",
    status_code=status.HTTP_204_NO_CONTENT,
    # 클라이언트용 API 가 아니다. 공개 명세에 실으면 FE 가 부를 것처럼 읽힌다.
    include_in_schema=False,
)
def put_review(session_id: SessionIdPath, body: ReviewUpsert, store: StoreDep) -> None:
    if store.get_session(session_id) is None:
        raise ApiError(ErrorCode.SESSION_NOT_FOUND, 404, "Session 을 찾을 수 없습니다.")

    # 자리가 없으면 만든다. 종료를 안 거친 세션이나 이 기능이 붙기 전에 끝난
    # 세션이라도, 결과가 왔는데 버리는 것보다 받는 편이 낫다.
    summary = store.ensure_summary(SessionSummary(session_id=session_id))
    if body.status in SHOWABLE:
        summary.complete(body.summary, body.key_points)
    else:
        summary.give_up()
    store.save_summary(summary)

    # 요약 본문은 남기지 않는다. 면접 내용이 그대로 로그에 쌓인다.
    logger.info(
        "최종 리뷰 수신 session_id=%s agent_status=%s → %s 핵심=%d개",
        session_id,
        body.status,
        summary.status.value,
        len(summary.key_points),
    )
