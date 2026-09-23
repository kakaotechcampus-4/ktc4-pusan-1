"""Agent → BE 꼬리질문 수신 — `POST /internal/v1/sessions/{sessionId}/suggestions`.

Agent 가 면접 중에 만든 꼬리질문을 하나씩 보낸다 (`irya_ai.backend.post_suggestion`).

⚠️ **아직 저장하지 않는다.** 꼬리질문 테이블이 없다 (#85). 검증하고 로그만 남긴 뒤
204 를 준다.

전사와 달리 여기서는 잃어도 덜 아프다. 꼬리질문은 면접관이 그 순간에 보면 쓸모가
있고 지나가면 가치가 크게 떨어지는 것이라, 재전송으로 되살릴 성질이 아니다. Agent
쪽도 실패를 로그만 남기고 다음 발화로 넘어간다 (#83).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import StoreDep
from app.api.internal.deps import require_internal_auth
from app.api.internal.schemas import SuggestionCreate
from app.core.errors import ApiError, ErrorCode

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_internal_auth)])

SessionIdPath = Annotated[str, Path(alias="sessionId")]


@router.post(
    "/sessions/{sessionId}/suggestions",
    status_code=status.HTTP_204_NO_CONTENT,
    # 클라이언트용 API 가 아니다. 공개 명세에 실으면 FE 가 부를 것처럼 읽힌다.
    include_in_schema=False,
)
def create_suggestion(
    session_id: SessionIdPath, body: SuggestionCreate, store: StoreDep
) -> None:
    if store.get_session(session_id) is None:
        raise ApiError(ErrorCode.SESSION_NOT_FOUND, 404, "Session 을 찾을 수 없습니다.")

    # TODO(#85): (session_id, suggestion_id) 로 저장한다.
    logger.info(
        "꼬리질문 수신 session_id=%s suggestion_id=%s type=%s 근거=%d개",
        session_id,
        body.suggestion_id,
        body.type,
        len(body.evidence_utterance_ids),
    )
