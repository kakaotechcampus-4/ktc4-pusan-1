"""세션 상태·입장 — 명세 `면접`·`진입` 카테고리.

지원자는 로그인하지 않는다. 그래서 상태 조회와 입장은 열어 두고, 시작 · 종료 · 요약은
그 면접의 주인만 부른다 (#130). 남의 세션은 없는 것과 같이 404 다.
"""

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import (
    MediaDep,
    OptionalUserDep,
    OwnedSessionDep,
    StoreDep,
    get_current_user,
)
from app.core.config import settings
from app.core.errors import LOGIN_REQUIRED, ApiError, ErrorCode, responses
from app.domain.models import (
    Role,
    Session,
    SessionStatus,
    SessionSummary,
    SummaryStatus,
)
from app.domain.store import Store
from app.schemas import (
    EndSessionResponse,
    JoinRequest,
    JoinResponse,
    SessionStateResponse,
    StartSessionResponse,
    SummaryContent,
    SummaryResponse,
)

router = APIRouter(prefix="/sessions", tags=["세션"])

# 명세의 path 파라미터는 camelCase 다.
# 파이썬 변수명은 snake_case 로 두고 alias 로 맞춘다.
SessionIdPath = Annotated[str, Path(alias="sessionId")]

_NOT_FOUND = (404, "Session을 찾을 수 없음 (남의 세션 포함)")


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
    interview = store.get_interview(session.interview_id)
    return SessionStateResponse(
        session_id=session.id,
        interview_id=session.interview_id,
        candidate_name=interview.candidate_name if interview else None,
        status=session.status,
        started_at=session.started_at,
        ended_at=session.ended_at,
        transcript_origin_at=session.transcript_origin_at,
    )


@router.post(
    "/{sessionId}/join",
    response_model=JoinResponse,
    summary="면접 입장",
    responses=responses(
        (401, "면접관으로 입장하는데 로그인이 안 됨"),
        (403, "면접관으로 입장하는데 이 면접의 주인이 아님"),
        (404, "Session을 찾을 수 없음"),
        (409, "이미 종료된 Session 등 현재 상태에서 입장할 수 없음"),
    ),
)
async def join_session(
    session_id: SessionIdPath,
    body: JoinRequest,
    user: OptionalUserDep,
    store: StoreDep,
    media: MediaDep,
) -> JoinResponse:
    """Session 입장 권한을 확인하고 LiveKit 접속 정보를 발급한다.

    지원자는 초대 링크에서 sessionId 를 전달받는다.

    토큰만 발급할 뿐 실제 입장은 클라이언트가 `livekitUrl` + `token` 으로
    LiveKit 에 직접 붙으면서 이뤄진다. 여러 번 불러도 되며 그때마다 새 토큰이 나온다.
    """
    session = _load(store, session_id)
    interview = store.get_interview(session.interview_id)

    # ponytail: 역할은 클라이언트가 고르고 서버는 INTERVIEWER 만 검증한다 (#130).
    #   면접관이 여럿이 되거나 역할이 셋 이상이면 서버가 역할을 정하는 쪽으로 옮긴다.
    # 상태 · 정원보다 먼저 본다 — 권한 없는 요청마다 LiveKit 을 부르지 않게.
    if body.role is Role.INTERVIEWER:
        # 토큰이 없거나 무효면 401 이다. FE 는 401 에만 토큰을 지우고 로그인으로
        # 보내므로, 403 을 주면 만료된 토큰을 쥔 면접관이 빠져나갈 길이 없다.
        owner = get_current_user(user)
        if interview is None or interview.interviewer_id != owner.id:
            raise ApiError(
                ErrorCode.ROLE_NOT_ALLOWED,
                403,
                "이 면접의 면접관만 면접관으로 입장할 수 있습니다.",
            )

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
        candidate_name=interview.candidate_name if interview else None,
        livekit_url=settings.livekit_url,
        token=issued.token,
        room_name=session.room_name,
    )


@router.post(
    "/{sessionId}/start",
    response_model=StartSessionResponse,
    summary="면접 시작",
    responses=responses(
        LOGIN_REQUIRED, _NOT_FOUND, (409, "현재 상태에서 시작할 수 없음")
    ),
)
def start_session(session: OwnedSessionDep, store: StoreDep) -> StartSessionResponse:
    """Session 을 면접 진행 상태로 변경하고 시작 시각을 기록한다.

    동시에 여러 번 불려도 **하나만 200 을 받고 나머지는 409** 다. 버튼을 두 번
    눌렀거나 응답이 늦어 클라이언트가 재시도한 경우에 닿는다.
    """
    # 애초에 시작할 수 없는 상태(이미 끝난 면접 등)를 DB 를 건드리기 전에 거른다.
    if not session.start():
        raise ApiError(
            ErrorCode.INVALID_SESSION_STATE, 409, "현재 상태에서 시작할 수 없습니다."
        )
    # 읽은 뒤 저장하기 전에 다른 요청이 먼저 시작해 버린 경우를 잡는다.
    # 위 검사와 중복이 아니다 — 저 검사는 메모리 안의 객체만 본다.
    if not store.save_session(session, expected_status=SessionStatus.WAITING):
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
        LOGIN_REQUIRED, _NOT_FOUND, (409, "현재 상태에서 종료할 수 없음")
    ),
)
async def end_session(
    session: OwnedSessionDep, store: StoreDep, media: MediaDep
) -> EndSessionResponse:
    """Session 을 종료 상태로 변경하고 종료 시각을 기록한다.

    참가자 disconnect 와 면접 종료는 별개다 — 참가자가 나가도 Session 은 살아 있고
    이 API 를 불러야 종료된다. 반대로 여기서는 LiveKit Room 을 닫아
    남아 있는 참가자를 끊는다.
    """
    read_status = session.status
    if not session.end():
        raise ApiError(
            ErrorCode.INVALID_SESSION_STATE, 409, "현재 상태에서 종료할 수 없습니다."
        )
    # LiveKit Room 을 닫기 전에 저장한다. close_room 이 실패해도 종료 상태는
    # 남아야 한다 — 방이 남는 건 정원 제한에 걸리는 정도지만, 상태가 안 남으면
    # 이미 끝난 면접에 다시 입장할 수 있게 된다.
    #
    # 읽은 상태 그대로일 때만 쓴다. 그 사이에 시작이 먼저 저장됐으면 조건 없이
    # 쓰는 순간 읽어 둔 값으로 시작 시각을 지운다 (#131). 상태가 같으면 시작 ·
    # 종료 시각도 그대로이므로 나머지 컬럼을 같이 써도 덮을 것이 없다.
    # ponytail: 시작과 겹치면 409 — 다시 누르면 끝난다. 자주 겹치면 종료가
    #   status · ended_at 만 쓰는 조건부 UPDATE 로 옮긴다.
    if not store.save_session(session, expected_status=read_status):
        raise ApiError(
            ErrorCode.INVALID_SESSION_STATE, 409, "현재 상태에서 종료할 수 없습니다."
        )
    # 요약을 기다리는 자리를 지금 만든다. 한도 판정의 기준점이 여기서 찍히므로
    # 조회 시점이 아니라 종료 시점이어야 한다 — 면접이 끝나고 한참 뒤에 화면을
    # 열었다고 해서 마감이 그때부터 다시 시작되면 안 된다.
    store.ensure_summary(SessionSummary(session_id=session.id))
    await media.close_room(session.room_name)
    assert session.ended_at is not None
    return EndSessionResponse(
        session_id=session.id, status=session.status, ended_at=session.ended_at
    )


@router.get(
    "/{sessionId}/summary",
    response_model=SummaryResponse,
    summary="면접 요약 조회",
    responses=responses(
        LOGIN_REQUIRED,
        _NOT_FOUND,
        (409, "아직 종료되지 않은 면접"),
    ),
)
def get_summary(session: OwnedSessionDep, store: StoreDep) -> SummaryResponse:
    """면접이 끝난 뒤의 짧은 요약을 조회한다.

    **상태는 저장된 값이다.** 면접이 끝나면 `PROCESSING` 으로 자리가 생기고,
    Agent 가 결과를 써 넣으면(`PUT /internal/v1/sessions/{id}/review`) `READY`,
    한도(`SUMMARY_TIMEOUT_SECONDS`, 기본 3분)를 넘기면 `FAILED` 다.

    **한도 판정을 여기서 한다.** 스케줄러를 두지 않는 이유는, 아무도 안 보는
    세션의 상태가 제때 안 바뀌어도 해가 없기 때문이다. 보는 순간 맞으면 된다.

    요약을 만드는 쪽(#70)이 아직 안 붙어 있어도 이 경로는 그대로 돈다 — 한도까지
    기다렸다 `FAILED` 로 간다. 붙고 나면 같은 코드가 `READY` 를 낸다.
    """
    summary = store.get_summary(session.id)

    if summary is None:
        if session.status is not SessionStatus.ENDED:
            raise ApiError(
                ErrorCode.INVALID_SESSION_STATE,
                409,
                "아직 종료되지 않은 면접입니다.",
            )
        # 이 기능이 붙기 전에 끝난 세션이다. 지금 자리를 만들어 준다 — 그 면접의
        # 요약은 어차피 안 오므로 한도를 넘기고 FAILED 가 된다.
        summary = store.ensure_summary(SessionSummary(session_id=session.id))

    # 한도 판정은 저장소가 한 문장으로 끝낸다. 여기서 읽고 판정하고 쓰면 그
    # 사이에 Agent 의 결과가 들어와 덮여 지워진다 (#115).
    #
    # 이미 끝난 요약은 부르지 않는다. 판정 대상이 PROCESSING 뿐이라 결과가 같고,
    # 조회마다 0행 UPDATE 와 재조회가 공짜로 나가는 것만 준다. 여기서 읽은 값이
    # 낡았더라도 손해는 없다 — PROCESSING 으로 낡았으면 아래에서 제대로 판정하고,
    # 종착 상태는 되돌아오지 않는다.
    if summary.status is SummaryStatus.PROCESSING:
        summary = store.expire_summary(session.id, settings.summary_timeout) or summary

    content = None
    if summary.status is SummaryStatus.READY:
        content = SummaryContent(
            overview=summary.overview, key_points=summary.key_points
        )
    return SummaryResponse(
        session_id=session.id,
        status=summary.status,
        content=content,
        duration_sec=_duration_sec(session),
    )


def _duration_sec(session: Session) -> int:
    if session.started_at is None or session.ended_at is None:
        return 0
    return max(0, int((session.ended_at - session.started_at).total_seconds()))
