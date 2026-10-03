"""면접 · 세션 생성 — 명세 `면접` 카테고리.

전부 로그인한 면접관의 것이다 (#144). 남의 면접은 없는 것과 똑같이 404 로 답한다 —
403 을 주면 그 id 가 있다는 것이 새어 나간다.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Path, UploadFile, status

from app.api.deps import CurrentUserDep, MediaDep, ParserDep, StoreDep
from app.core.config import settings
from app.core.errors import ApiError, ErrorCode, responses
from app.core.uploads import read_upload
from app.domain.models import Interview, Resume, Session, User
from app.domain.store import Store
from app.schemas import (
    ContextDocResponse,
    CreateInterviewRequest,
    CreateSessionResponse,
    InterviewListItem,
    InterviewResponse,
    LatestSession,
    ReviewProcessingResponse,
)

router = APIRouter(prefix="/interviews", tags=["면접"])

InterviewIdPath = Annotated[str, Path(alias="interviewId")]

_UNAUTHORIZED = (401, "로그인이 필요함")
_NOT_FOUND = (404, "면접을 찾을 수 없음 (남의 면접 포함)")


def _owned(store: Store, interview_id: str, user: User) -> Interview:
    interview = store.get_interview(interview_id)
    if interview is None or interview.interviewer_id != user.id:
        raise ApiError(ErrorCode.INTERVIEW_NOT_FOUND, 404, "면접을 찾을 수 없습니다.")
    return interview


def _to_response(interview: Interview) -> InterviewResponse:
    return InterviewResponse(
        interview_id=interview.id,
        interviewer_id=interview.interviewer_id,
        candidate_name=interview.candidate_name,
        created_at=interview.created_at,
    )


def _clean_candidate_name(name: str | None) -> str | None:
    if name is None:
        return None
    stripped = name.strip()
    return stripped or None


@router.post(
    "",
    response_model=InterviewResponse,
    status_code=201,
    summary="면접 생성",
    responses=responses(_UNAUTHORIZED, (422, "요청값 검증 실패")),
)
def create_interview(
    body: CreateInterviewRequest, store: StoreDep, user: CurrentUserDep
) -> InterviewResponse:
    """면접관이 새로운 면접 정보를 생성한다.

    Session 과 LiveKit Room 은 여기서 만들지 않는다 —
    `POST /interviews/{interviewId}/sessions` 가 담당한다.
    """
    interview = Interview(
        interviewer_id=user.id,
        candidate_name=_clean_candidate_name(body.candidate_name),
    )
    store.add_interview(interview)
    return _to_response(interview)


@router.get(
    "",
    response_model=list[InterviewListItem],
    summary="내 면접 목록",
    responses=responses(_UNAUTHORIZED),
)
def list_interviews(store: StoreDep, user: CurrentUserDep) -> list[InterviewListItem]:
    """내가 만든 면접을 최신순으로, 각 면접의 가장 최근 Session 과 함께 준다.

    지원자 목록 화면이 이름 · 면접 일시 · 길이 · 요약/기록 링크를 여기서 그린다.
    직무 · 검토 상태 · 확인 항목은 서버에 아직 없는 값이라 싣지 않는다.
    """
    # ponytail: 페이지네이션 없음. 면접관 한 명의 면접이 수백 건을 넘으면
    # cursor 를 붙인다.
    return [
        InterviewListItem(
            interview_id=interview.id,
            candidate_name=interview.candidate_name,
            created_at=interview.created_at,
            latest_session=None
            if session is None
            else LatestSession(
                session_id=session.id,
                status=session.status,
                started_at=session.started_at,
                ended_at=session.ended_at,
            ),
        )
        for interview, session in store.list_interviews(user.id)
    ]


@router.get(
    "/{interviewId}",
    response_model=InterviewResponse,
    summary="면접 조회",
    responses=responses(_UNAUTHORIZED, _NOT_FOUND),
)
def get_interview(
    interview_id: InterviewIdPath, store: StoreDep, user: CurrentUserDep
) -> InterviewResponse:
    """생성된 면접의 기본 정보를 조회한다."""
    return _to_response(_owned(store, interview_id, user))


@router.post(
    "/{interviewId}/sessions",
    response_model=CreateSessionResponse,
    status_code=201,
    summary="면접 Session 생성",
    responses=responses(_UNAUTHORIZED, _NOT_FOUND),
)
async def create_session(
    interview_id: InterviewIdPath,
    store: StoreDep,
    media: MediaDep,
    user: CurrentUserDep,
) -> CreateSessionResponse:
    """생성된 면접에 실제 화상면접 Session 을 만들고 지원자 초대 링크를 발급한다.

    LiveKit Room 을 미리 만든다. 입장 시 자동 생성되기는 하지만
    `max_participants` 같은 설정을 적용하려면 사전 생성이 필요하다.
    """
    interview = _owned(store, interview_id, user)

    session = Session(interview_id=interview_id)
    await media.ensure_room(session.room_name)
    store.add_session(session)

    return CreateSessionResponse(
        session_id=session.id,
        interview_id=session.interview_id,
        candidate_name=interview.candidate_name,
        status=session.status,
        invite_url=f"{settings.frontend_origin}{settings.invite_path}/{session.id}",
        created_at=session.created_at,
    )


@router.get(
    "/{interviewId}/review",
    # 지금 나가는 건 PROCESSING 한 갈래뿐이라 그것만 선언한다.
    # READY 는 아직 합의 전이라 schemas.py 에 모델로만 둔다 — 합의 전 형태를
    # OpenAPI 에 실으면 FE·AI 가 확정된 계약으로 읽는다.
    response_model=ReviewProcessingResponse,
    status_code=202,
    summary="면접 기록 조회",
    responses=responses(_UNAUTHORIZED, _NOT_FOUND),
)
def get_review(
    interview_id: InterviewIdPath, store: StoreDep, user: CurrentUserDep
) -> ReviewProcessingResponse:
    """면접이 끝난 뒤의 기록(녹화 · 타임라인 · AI 서술)을 조회한다.

    **지금은 항상 `PROCESSING` 을 돌려준다.** 면접 존재 여부만 확인하는 단계다.
    FE 는 이 분기를 이미 갖고 있어(`ReviewResponse`) 화면이 로딩 상태로 뜬다.

    READY 를 채우려면 셋이 더 필요하고, 전부 아직 없다.

      moments   AI 의 build_timeline() 결과. ai/ 패키지를 BE 가 어떻게 부를지 미정
      recording LiveKit Egress. compose 에 컨테이너도 저장소도 없다
      aiReview  요약 파이프라인. moments 와 다른 산출물이다

    202 로 두는 건 FE 가 그렇게 읽기 때문이다 — "준비 전에는 202 와 PROCESSING".
    준비가 끝나면 200 + READY 로 바뀐다.
    """
    _owned(store, interview_id, user)
    # etaSec 은 비운다. 추정할 근거가 아직 없는데 숫자를 주면 FE 가 그걸 믿는다.
    return ReviewProcessingResponse()


@router.post(
    "/{interviewId}/resume",
    response_model=ContextDocResponse,
    status_code=status.HTTP_201_CREATED,
    summary="지원자 이력서 업로드",
    responses=responses(
        _UNAUTHORIZED,
        _NOT_FOUND,
        (413, "파일이 너무 큼"),
        (415, "지원하지 않는 형식"),
    ),
)
async def upload_resume(
    interview_id: InterviewIdPath,
    store: StoreDep,
    user: CurrentUserDep,
    parser: ParserDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
) -> ContextDocResponse:
    """지원자 이력서를 올린다. **PDF 만 받는다.**

    **면접 한 건에 한 장이고 다시 올리면 덮어쓴다.** FE 가 목록도 삭제도 두지 않은
    것이 그 전제다(#81) — 새 이력서를 올리면 앞의 것은 쓸 일이 없다.

    응답은 기업 컨텍스트 문서와 같은 모양(`ContextDoc`)이다. FE 가 같은 카드
    컴포넌트로 그린다.

    본문은 기업 컨텍스트 문서와 같이 응답 뒤에 따로 뽑는다(#143). 응답은 `parsing`
    이다. 꼬리질문과 리포트가 이 본문을 쓴다(#70).
    """
    _owned(store, interview_id, user)

    name, kind, content = await read_upload(file)
    resume = Resume(
        interview_id=interview_id, name=name, kind=kind, size_bytes=len(content)
    )
    store.save_resume(resume, content)
    background.add_task(
        lambda: store.finish_resume(
            interview_id, resume.id, parser.extract_text(resume.name, content)
        )
    )
    return ContextDocResponse(
        id=resume.id,
        name=resume.name,
        kind=resume.kind,
        size_bytes=resume.size_bytes,
        status=resume.status,
    )
