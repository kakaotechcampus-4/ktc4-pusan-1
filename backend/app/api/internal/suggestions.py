"""Agent → BE 꼬리질문 수신 — `POST /internal/v1/sessions/{sessionId}/suggestions`.

Agent 가 면접 중에 만든 꼬리질문을 하나씩 보낸다 (`irya_ai.backend.post_suggestion`).

받은 꼬리질문은 `suggestion` 에 저장하고 204 를 준다 (#85). 같은 `suggestionId` 가
다시 오면 처음 것을 남긴다 — Agent 의 재시도다.

처음 들어온 것이면 면접관에게 LiveKit 데이터 패킷으로 바로 보낸다 (#212). 지원자에게는
가지 않는다. 보내지 못해도 204 다 — 저장은 됐고, 놓친 것은 FE 가 조회 API
(`GET /api/v1/sessions/{sessionId}/suggestions`)로 되살린다. 여기서 실패를 내면
Agent 는 다시 보내지 않으므로 알릴 곳도 없다.

전사와 달리 여기서는 잃어도 덜 아프다. 꼬리질문은 면접관이 그 순간에 보면 쓸모가
있고 지나가면 가치가 크게 떨어지는 것이라, 재전송으로 되살릴 성질이 아니다. Agent
쪽도 실패를 로그만 남기고 다음 발화로 넘어간다 (#83).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import MediaDep, StoreDep
from app.api.internal.deps import require_internal_auth
from app.api.internal.schemas import SuggestionCreate
from app.core.errors import ApiError, ErrorCode
from app.domain.models import Role, Suggestion
from app.schemas import SuggestionResponse

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_internal_auth)])

SessionIdPath = Annotated[str, Path(alias="sessionId")]

#: FE 가 `RoomEvent.DataReceived` 에서 거르는 토픽. 자막(`irya.transcript.v1`)과 짝이다.
SUGGESTION_TOPIC = "irya.suggestion.v1"


@router.post(
    "/sessions/{sessionId}/suggestions",
    status_code=status.HTTP_204_NO_CONTENT,
    # 클라이언트용 API 가 아니다. 공개 명세에 실으면 FE 가 부를 것처럼 읽힌다.
    include_in_schema=False,
)
async def create_suggestion(
    session_id: SessionIdPath, body: SuggestionCreate, store: StoreDep, media: MediaDep
) -> None:
    session = await run_in_threadpool(store.get_session, session_id)
    if session is None:
        raise ApiError(ErrorCode.SESSION_NOT_FOUND, 404, "Session 을 찾을 수 없습니다.")

    suggestion = Suggestion(
        session_id=session_id,
        suggestion_id=body.suggestion_id,
        content=body.content,
        evidence_utterance_ids=body.evidence_utterance_ids,
    )
    added = await run_in_threadpool(store.add_suggestion, suggestion)
    logger.info(
        "꼬리질문 수신 session_id=%s suggestion_id=%s 근거=%d개 새것=%s",
        session_id,
        body.suggestion_id,
        len(body.evidence_utterance_ids),
        added,
    )
    if not added:
        return

    packet = SuggestionResponse.model_validate(suggestion, from_attributes=True)
    try:
        await media.send_data(
            session.room_name,
            packet.model_dump_json(by_alias=True).encode(),
            topic=SUGGESTION_TOPIC,
            to=[Role.INTERVIEWER.value],
        )
    except Exception:
        logger.warning(
            "꼬리질문 전달 실패 session_id=%s suggestion_id=%s",
            session_id,
            body.suggestion_id,
            exc_info=True,
        )
