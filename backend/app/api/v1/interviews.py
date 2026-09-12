"""면접 · 세션 생성 — 명세 `면접` 카테고리."""

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import MediaDep, StoreDep
from app.core.config import settings
from app.core.errors import ApiError, ErrorCode, responses
from app.domain.models import Interview, Session
from app.schemas import CreateInterviewRequest, CreateSessionResponse, InterviewResponse

router = APIRouter(prefix="/interviews", tags=["면접"])

InterviewIdPath = Annotated[str, Path(alias="interviewId")]


def _to_response(interview: Interview) -> InterviewResponse:
    return InterviewResponse(
        interview_id=interview.id,
        interviewer_id=interview.interviewer_id,
        created_at=interview.created_at,
    )


@router.post(
    "",
    response_model=InterviewResponse,
    status_code=201,
    summary="면접 생성",
    responses=responses((422, "요청값 검증 실패")),
)
def create_interview(
    body: CreateInterviewRequest, store: StoreDep
) -> InterviewResponse:
    """면접관이 새로운 면접 정보를 생성한다.

    Session 과 LiveKit Room 은 여기서 만들지 않는다 —
    `POST /interviews/{interviewId}/sessions` 가 담당한다.
    """
    interview = Interview(interviewer_id=body.interviewer_id)
    store.add_interview(interview)
    return _to_response(interview)


@router.get(
    "/{interviewId}",
    response_model=InterviewResponse,
    summary="면접 조회",
    responses=responses((404, "면접을 찾을 수 없음")),
)
def get_interview(interview_id: InterviewIdPath, store: StoreDep) -> InterviewResponse:
    """생성된 면접의 기본 정보를 조회한다."""
    interview = store.get_interview(interview_id)
    if interview is None:
        raise ApiError(ErrorCode.INTERVIEW_NOT_FOUND, 404, "면접을 찾을 수 없습니다.")
    return _to_response(interview)


@router.post(
    "/{interviewId}/sessions",
    response_model=CreateSessionResponse,
    status_code=201,
    summary="면접 Session 생성",
    responses=responses((404, "면접을 찾을 수 없음")),
)
async def create_session(
    interview_id: InterviewIdPath, store: StoreDep, media: MediaDep
) -> CreateSessionResponse:
    """생성된 면접에 실제 화상면접 Session 을 만들고 지원자 초대 링크를 발급한다.

    LiveKit Room 을 미리 만든다. 입장 시 자동 생성되기는 하지만
    `max_participants` 같은 설정을 적용하려면 사전 생성이 필요하다.
    """
    if store.get_interview(interview_id) is None:
        raise ApiError(ErrorCode.INTERVIEW_NOT_FOUND, 404, "면접을 찾을 수 없습니다.")

    session = Session(interview_id=interview_id)
    await media.ensure_room(session.room_name)
    store.add_session(session)

    return CreateSessionResponse(
        session_id=session.id,
        interview_id=session.interview_id,
        status=session.status,
        invite_url=f"{settings.frontend_origin}{settings.invite_path}/{session.id}",
        created_at=session.created_at,
    )
