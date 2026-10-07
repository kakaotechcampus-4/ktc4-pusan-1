"""면접 · 세션 생성 — 명세 `면접` 카테고리.

전부 면접관 전용이라 로그인이 필요하고, 남의 면접은 없는 것과 같이 404 다 (#130).
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import (
    CurrentUserDep,
    MediaDep,
    OwnedInterviewDep,
    ParserDep,
    StoreDep,
    get_owned_interview,
)
from app.core.config import settings
from app.core.errors import LOGIN_REQUIRED, responses
from app.core.uploads import read_upload
from app.domain.models import (
    Context,
    Interview,
    InterviewPrep,
    Resume,
    Session,
    SummaryStatus,
)
from app.schemas import (
    ContextDocResponse,
    CreateInterviewRequest,
    CreateSessionResponse,
    InterviewerSummary,
    InterviewListItem,
    InterviewListResponse,
    InterviewResponse,
    ReviewProcessingResponse,
)

router = APIRouter(prefix="/interviews", tags=["면접"])

_NOT_FOUND = (404, "면접을 찾을 수 없음 (남의 면접 포함)")


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
    responses=responses(LOGIN_REQUIRED, (422, "요청값 검증 실패")),
)
def create_interview(
    body: CreateInterviewRequest, user: CurrentUserDep, store: StoreDep
) -> InterviewResponse:
    """면접관이 새로운 면접 정보를 생성한다.

    Session 과 LiveKit Room 은 여기서 만들지 않는다 —
    `POST /interviews/{interviewId}/sessions` 가 담당한다.

    면접의 주인(`interviewerId`)은 토큰의 사용자다. 요청 본문으로 받으면 아무 이름으로나
    면접을 만들 수 있어, 그 면접을 주인만 다룬다는 판단이 서지 않는다.
    """
    interview = Interview(
        interviewer_id=user.id,
        candidate_name=_clean_candidate_name(body.candidate_name),
    )
    store.add_interview(interview)
    return _to_response(interview)


@router.get(
    "",
    response_model=InterviewListResponse,
    summary="내 면접 목록",
    responses=responses(LOGIN_REQUIRED),
)
def list_interviews(user: CurrentUserDep, store: StoreDep) -> InterviewListResponse:
    """내가 만든 면접을 최신순으로 준다. 필터 · 정렬은 FE 가 한다 (#137 1-1).

    면접관은 늘 나라서 `interviewer` 는 토큰의 사용자고, 직무는 내 컨텍스트에서 온다.
    """
    # ponytail: 페이지네이션 없음. 면접관 한 명의 면접이 수백 건을 넘으면
    # cursor 를 붙인다.
    role = store.ensure_context(Context(owner_id=user.id)).role
    interviewer = InterviewerSummary(nickname=user.nickname)
    return InterviewListResponse(
        items=[
            _to_list_item(interview, session, summary, role, interviewer)
            for interview, session, summary in store.list_interviews(user.id)
        ]
    )


def _to_list_item(
    interview: Interview,
    session: Session | None,
    summary: SummaryStatus | None,
    role: str,
    interviewer: InterviewerSummary,
) -> InterviewListItem:
    began = (
        None if session is None else session.started_at or session.transcript_origin_at
    )
    ended = None if session is None else session.ended_at
    return InterviewListItem(
        interview_id=interview.id,
        candidate_name=interview.candidate_name,
        role=role,
        interviewer=interviewer,
        interviewed_at=began,
        duration_sec=None
        if began is None or ended is None
        else int((ended - began).total_seconds()),
        review_status="PENDING",
        summary_status=summary,
        counts=None,
    )


@router.get(
    "/{interviewId}",
    response_model=InterviewResponse,
    summary="면접 조회",
    responses=responses(LOGIN_REQUIRED, _NOT_FOUND),
)
def get_interview(interview: OwnedInterviewDep) -> InterviewResponse:
    """생성된 면접의 기본 정보를 조회한다."""
    return _to_response(interview)


@router.post(
    "/{interviewId}/sessions",
    response_model=CreateSessionResponse,
    status_code=201,
    summary="면접 Session 생성",
    responses=responses(LOGIN_REQUIRED, _NOT_FOUND),
)
async def create_session(
    interview: OwnedInterviewDep, store: StoreDep, media: MediaDep
) -> CreateSessionResponse:
    """생성된 면접에 실제 화상면접 Session 을 만들고 지원자 초대 링크를 발급한다.

    LiveKit Room 을 미리 만든다. 입장 시 자동 생성되기는 하지만
    `max_participants` 같은 설정을 적용하려면 사전 생성이 필요하다.
    """
    session = Session(interview_id=interview.id)
    await media.ensure_room(session.room_name)
    # 저장소는 동기다. async 라우트가 그대로 부르면 그동안 이벤트 루프가 멈춘다 (#133).
    # 면접 전 분석을 요청한다(#162). 이미 있으면 그대로다 — 세션을 다시 만들 때마다
    # 다시 돌리지 않는다. 실패했으면 다시 요청하고, 이력서를 바꾸면 다시 돈다.
    #
    # 세션보다 먼저 연다. 거꾸로면 세션 저장과 이 줄 사이에 죽었을 때 자리가 영영 안
    # 열린다 — 이력서 재요청은 UPDATE 라 없는 자리를 못 연다. 자리만 있고 세션이
    # 없으면 작업이 나가지 않으니(할 일 조회가 세션을 조인한다) 먼저 열어도 된다.
    await run_in_threadpool(store.ensure_prep, InterviewPrep(interview_id=interview.id))
    await run_in_threadpool(store.add_session, session)

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
    responses=responses(LOGIN_REQUIRED, _NOT_FOUND),
    dependencies=[Depends(get_owned_interview)],
)
def get_review() -> ReviewProcessingResponse:
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
    # etaSec 은 비운다. 추정할 근거가 아직 없는데 숫자를 주면 FE 가 그걸 믿는다.
    return ReviewProcessingResponse()


@router.post(
    "/{interviewId}/resume",
    response_model=ContextDocResponse,
    status_code=status.HTTP_201_CREATED,
    summary="지원자 이력서 업로드",
    responses=responses(
        LOGIN_REQUIRED,
        _NOT_FOUND,
        (413, "파일이 너무 큼"),
        (415, "지원하지 않는 형식"),
    ),
)
async def upload_resume(
    interview: OwnedInterviewDep,
    store: StoreDep,
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
    name, kind, content = await read_upload(file)
    resume = Resume(
        interview_id=interview.id, name=name, kind=kind, size_bytes=len(content)
    )
    await run_in_threadpool(store.save_resume, resume, content)
    # 새 이력서로 면접 전 분석을 다시 돌린다(#162). 세션을 만들기 전이면 자리가 없어
    # 아무 일도 없고, 세션을 만들 때 열린다. 본문 추출이 끝나야 작업이 나간다.
    await run_in_threadpool(store.restart_prep, interview.id)
    background.add_task(
        lambda: store.finish_resume(
            interview.id, resume.id, parser.extract_text(resume.name, content)
        )
    )
    return ContextDocResponse(
        id=resume.id,
        name=resume.name,
        kind=resume.kind,
        size_bytes=resume.size_bytes,
        status=resume.status,
    )
