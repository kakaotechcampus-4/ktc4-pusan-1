"""세션 상태·입장 — 명세 `면접`·`진입` 카테고리."""

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import MediaDep, StoreDep
from app.core.config import settings
from app.core.errors import ApiError, ErrorCode, responses
from app.domain.models import Session, SessionStatus
from app.domain.store import Store
from app.schemas import (
    EndSessionResponse,
    JoinRequest,
    JoinResponse,
    SessionStateResponse,
    StartSessionResponse,
)

router = APIRouter(prefix="/sessions", tags=["세션"])

# 명세의 path 파라미터는 camelCase 다.
# 파이썬 변수명은 snake_case 로 두고 alias 로 맞춘다.
SessionIdPath = Annotated[str, Path(alias="sessionId")]


def _load(store: Store, session_id: str) -> Session:
    session = store.get_session(session_id)
    if session is None:
        raise ApiError(ErrorCode.SESSION_NOT_FOUND, 404, "Session 을 찾을 수 없습니다.")
    return session


@router.get(
    "/{sessionId}",
    response_model=SessionStateResponse,
    summary="Session 상태 조회",
    responses=responses((404, "Session을 찾을 수 없음")),
)
def get_session(session_id: SessionIdPath, store: StoreDep) -> SessionStateResponse:
    """현재 화상면접 Session 의 진행 상태를 조회한다.

    새로고침·재접속 시 상태 복구 용도다.
    """
    session = _load(store, session_id)
    return SessionStateResponse(
        session_id=session.id,
        interview_id=session.interview_id,
        status=session.status,
        started_at=session.started_at,
        ended_at=session.ended_at,
    )


@router.post(
    "/{sessionId}/join",
    response_model=JoinResponse,
    summary="면접 입장",
    responses=responses(
        (404, "Session을 찾을 수 없음"),
        (409, "이미 종료된 Session 등 현재 상태에서 입장할 수 없음"),
    ),
)
async def join_session(
    session_id: SessionIdPath, body: JoinRequest, store: StoreDep, media: MediaDep
) -> JoinResponse:
    """Session 입장 권한을 확인하고 LiveKit 접속 정보를 발급한다.

    지원자는 초대 링크에서 sessionId 를 전달받는다.

    토큰만 발급할 뿐 실제 입장은 클라이언트가 `livekitUrl` + `token` 으로
    LiveKit 에 직접 붙으면서 이뤄진다. 여러 번 불러도 되며 그때마다 새 토큰이 나온다.
    """
    session = _load(store, session_id)
    if session.status is SessionStatus.ENDED:
        raise ApiError(ErrorCode.SESSION_ENDED, 409, "이미 종료된 Session 입니다.")

    # 정원은 LiveKit 이 접속 시점에 강제한다. 여기 검사는 사전 안내용이고
    # 조회와 접속 사이의 경쟁 조건까지 막지는 못한다.
    in_room = await media.participant_count(session.room_name)
    if in_room >= settings.room_max_participants:
        raise ApiError(ErrorCode.ROOM_FULL, 409, "정원이 찼습니다.")

    issued = media.issue_token(session.room_name, body.role)
    return JoinResponse(
        session_id=session.id,
        livekit_url=settings.livekit_url,
        token=issued.token,
        room_name=session.room_name,
    )


@router.post(
    "/{sessionId}/start",
    response_model=StartSessionResponse,
    summary="면접 시작",
    responses=responses(
        (404, "Session을 찾을 수 없음"), (409, "현재 상태에서 시작할 수 없음")
    ),
)
def start_session(session_id: SessionIdPath, store: StoreDep) -> StartSessionResponse:
    """Session 을 면접 진행 상태로 변경하고 시작 시각을 기록한다."""
    session = _load(store, session_id)
    if not session.start():
        raise ApiError(
            ErrorCode.INVALID_SESSION_STATE, 409, "현재 상태에서 시작할 수 없습니다."
        )
    assert session.started_at is not None
    return StartSessionResponse(
        session_id=session.id, status=session.status, started_at=session.started_at
    )


@router.post(
    "/{sessionId}/end",
    response_model=EndSessionResponse,
    summary="면접 종료",
    responses=responses(
        (404, "Session을 찾을 수 없음"), (409, "현재 상태에서 종료할 수 없음")
    ),
)
async def end_session(
    session_id: SessionIdPath, store: StoreDep, media: MediaDep
) -> EndSessionResponse:
    """Session 을 종료 상태로 변경하고 종료 시각을 기록한다.

    참가자 disconnect 와 면접 종료는 별개다 — 참가자가 나가도 Session 은 살아 있고
    이 API 를 불러야 종료된다. 반대로 여기서는 LiveKit Room 을 닫아
    남아 있는 참가자를 끊는다.
    """
    session = _load(store, session_id)
    if not session.end():
        raise ApiError(
            ErrorCode.INVALID_SESSION_STATE, 409, "현재 상태에서 종료할 수 없습니다."
        )
    await media.close_room(session.room_name)
    assert session.ended_at is not None
    return EndSessionResponse(
        session_id=session.id, status=session.status, ended_at=session.ended_at
    )
