"""면접 · 세션 생성 — 명세 `면접` 카테고리.

전부 면접관 전용이라 로그인이 필요하고, 남의 면접은 없는 것과 같이 404 다 (#130).
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, UploadFile, status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import (
    CurrentUserDep,
    MediaDep,
    OwnedInterviewDep,
    ParserDep,
    StoreDep,
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
    SessionSummary,
    SummaryStatus,
)
from app.domain.store import Store
from app.schemas import (
    ContextDocResponse,
    CreateInterviewRequest,
    CreateSessionResponse,
    InterviewerSummary,
    InterviewListItem,
    InterviewListResponse,
    InterviewResponse,
    ReviewCandidate,
    ReviewCounts,
    ReviewCoverage,
    ReviewFinding,
    ReviewMoment,
    ReviewProcessingResponse,
    ReviewResponse,
    SummaryContent,
)
from app.services.review import build_review

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
    items = []
    for interview, session, summary in store.list_interviews(user.id):
        shown, counts = (
            (summary, None)
            if session is None
            else _shown_summary(store, interview, session, summary)
        )
        items.append(
            _to_list_item(interview, session, shown, counts, role, interviewer)
        )
    return InterviewListResponse(items=items)


def _shown_summary(
    store: Store, interview: Interview, session: Session, status: SummaryStatus | None
) -> tuple[SummaryStatus | None, ReviewCounts | None]:
    """보여 줄 요약 상태와 집계. 집계는 READY 일 때만, 상세와 같은 계산으로.

    한도를 넘긴 PROCESSING 은 FAILED 로 **보여 줄 뿐** 쓰지 않는다 — 문서의
    `shown_status` 와 같다. 판정과 저장은 요약 · 상세 조회가 한다.
    """
    # ponytail: READY 한 줄마다 쿼리 3개(N+1). 수백 건이면 LATERAL 로 한 번에 읽는다.
    if status is not SummaryStatus.PROCESSING and status is not SummaryStatus.READY:
        return status, None
    summary = store.get_summary(session.id)
    if summary is None:
        return status, None
    if summary.overdue(settings.summary_timeout):
        return SummaryStatus.FAILED, None
    if summary.status is not SummaryStatus.READY:
        return summary.status, None
    prep = store.get_prep(interview.id) or InterviewPrep(interview_id=interview.id)
    counts = build_review(
        prep.competencies,
        prep.resume_claims,
        summary.moments,
        summary.findings,
        store.list_marks(session.id),
    ).counts()
    return summary.status, ReviewCounts.model_validate(counts)


def _timing(session: Session | None) -> tuple[datetime | None, int | None]:
    """면접 시각과 길이. 「시작」을 안 눌렀으면 첫 입장 시각으로 대신한다 (#145).

    둘 다 없으면(아무도 입장하지 않고 끝낸 면접) 시각과 길이 모두 None 이다.
    """
    began = (
        None if session is None else session.started_at or session.transcript_origin_at
    )
    ended = None if session is None else session.ended_at
    if began is None or ended is None:
        return began, None
    return began, int((ended - began).total_seconds())


def _to_list_item(
    interview: Interview,
    session: Session | None,
    summary: SummaryStatus | None,
    counts: ReviewCounts | None,
    role: str,
    interviewer: InterviewerSummary,
) -> InterviewListItem:
    began, duration = _timing(session)
    return InterviewListItem(
        interview_id=interview.id,
        candidate_name=interview.candidate_name,
        role=role,
        interviewer=interviewer,
        interviewed_at=began,
        duration_sec=duration,
        review_status=interview.review_status,
        summary_status=summary,
        counts=counts,
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
    response_model=ReviewResponse,
    summary="면접 기록 조회",
    responses={
        202: {"model": ReviewProcessingResponse, "description": "준비 중"},
        **responses(LOGIN_REQUIRED, _NOT_FOUND),
    },
)
def get_review(
    interview: OwnedInterviewDep, user: CurrentUserDep, store: StoreDep
) -> ReviewResponse | JSONResponse:
    """면접이 끝난 뒤의 검토 화면 — 요약 · coverage · 타임라인 · 검토 항목 (#137 1-2).

    기준 세션은 그 면접에서 가장 나중에 끝난 세션이다(목록과 같다). 끝난 세션이
    없거나 요약이 아직 PROCESSING 이면 202 다. FE 는 그동안 다시 조회한다.

    **요약이 FAILED 여도 200 이다** (#163). `summary` 는 null 이고 moments ·
    findings 는 비며 coverage 는 역량 전부 MISSING 이다. 메모 · 검토 확정은 AI
    결과와 상관없이 할 수 있어야 한다.
    """
    session = store.last_ended_session(interview.id)
    if session is None:
        return _processing()
    # 요약 API(`GET /sessions/{id}/summary`)와 같은 판정이다. 자리가 없으면(이 기능
    # 전에 끝난 세션) 만들고, PROCESSING 은 한도를 본다 — 아무도 요약 화면을 열지
    # 않아도 상세는 열려야 한다.
    summary = store.get_summary(session.id) or store.ensure_summary(
        SessionSummary(session_id=session.id)
    )
    if summary.status is SummaryStatus.PROCESSING:
        summary = store.expire_summary(session.id, settings.summary_timeout) or summary
    if summary.status is SummaryStatus.PROCESSING:
        return _processing()

    ready = summary.status is SummaryStatus.READY
    prep = store.get_prep(interview.id) or InterviewPrep(interview_id=interview.id)
    review = build_review(
        prep.competencies,
        prep.resume_claims,
        summary.moments if ready else [],
        summary.findings if ready else [],
        store.list_marks(session.id),
    )
    began, duration = _timing(session)
    return ReviewResponse(
        summary_status="READY" if ready else "FAILED",
        interview_id=interview.id,
        session_id=session.id,
        candidate=ReviewCandidate(
            name=interview.candidate_name,
            role=store.ensure_context(Context(owner_id=user.id)).role,
        ),
        interviewer=InterviewerSummary(nickname=user.nickname),
        interviewed_at=began,
        duration_sec=duration,
        review_status=interview.review_status,
        reviewed_at=interview.reviewed_at,
        memo=interview.memo,
        summary=SummaryContent(overview=summary.overview, key_points=summary.key_points)
        if ready
        else None,
        coverage=[ReviewCoverage.model_validate(c) for c in review.coverage],
        moments=[ReviewMoment.model_validate(m) for m in review.moments],
        findings=[ReviewFinding.model_validate(f) for f in review.findings],
    )


def _processing() -> JSONResponse:
    # etaSec 은 비운다. 추정할 근거가 없는데 숫자를 주면 FE 가 그걸 믿는다.
    body = ReviewProcessingResponse().model_dump(by_alias=True)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body)


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
