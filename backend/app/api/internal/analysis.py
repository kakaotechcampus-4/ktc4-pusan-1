"""AI 분석 작업 — 할 일 조회 · 컨텍스트 · 면접 전 결과 (#162, #137 2-2 ~ 2-4).

AI 폴러가 N초마다 할 일을 묻고, 받은 작업의 컨텍스트를 읽어 분석한 뒤 결과를 써
넣는다. 한 번에 하나라 따로 큐를 두지 않는다 — 「할 일이 있다」는 사실이 DB 의
PROCESSING 행이다.

    GET /jobs/pending                  → {kind, sessionId, interviewId, requestedAt}
                                         또는 null
    GET /sessions/{sessionId}/context  → AI InterviewContext + 이력서 본문 + 전사
    PUT /interviews/{interviewId}/prep → 204

지금은 PREP 만 내준다. 면접 후 분석(REVIEW)은 #164 에서 같은 조회에 붙는다.

**재시도는 따로 없다.** 폴러가 죽으면 행이 PROCESSING 으로 남아 다음 조회에서 다시
나가고, 한도를 넘기면 FAILED 로 빠진다. FAILED 는 그 면접의 세션을 다시 만들거나
이력서를 다시 올리면 다시 요청된다. 면접 전 분석이 없거나 실패해도 면접은 진행된다
— 꼬리질문이 역량 · 주장 없이 만들어질 뿐이다 (#137 3장).
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import StoreDep
from app.api.internal.deps import require_internal_auth
from app.api.internal.schemas import PendingJob, PrepUpsert
from app.core.config import settings
from app.core.errors import ApiError, ErrorCode
from app.domain.models import (
    Context,
    DocCategory,
    InterviewPrep,
    Job,
    SummaryStatus,
    utcnow,
)

logger = logging.getLogger(__name__)

# 클라이언트용 API 가 아니다. 공개 명세에 실으면 FE 가 부를 것처럼 읽힌다.
router = APIRouter(
    dependencies=[Depends(require_internal_auth)], include_in_schema=False
)

SessionIdPath = Annotated[str, Path(alias="sessionId")]
InterviewIdPath = Annotated[str, Path(alias="interviewId")]


@router.get("/jobs/pending", response_model=PendingJob | None)
def pending_job(store: StoreDep) -> Job | None:
    # 한도는 요약 한도에 추출 한도를 더한다. 이력서 · JD 추출을 기다리는 동안에도
    # 요청 시각부터 시계가 가므로, 요약 한도만 주면 추출이 늦은 면접은 내주기도
    # 전에 FAILED 가 된다.
    #
    # `Job` 을 그대로 돌려주면 FastAPI 가 `PendingJob` 으로 옮겨 camelCase 로 낸다.
    return store.next_prep(
        settings.summary_timeout + settings.doc_parse_timeout,
        settings.doc_parse_timeout,
    )


@router.get("/sessions/{sessionId}/context")
def get_context(session_id: SessionIdPath, store: StoreDep) -> dict[str, Any]:
    """AI `InterviewContext` 에 이력서 본문과 전사를 더한 것 (#137 2-3). 면접 전 작업 ·
    워커 · 면접 후 작업이 같은 것을 읽는다.

    모양은 AI 쪽 모델이 기준이라 여기서 모델을 다시 두지 않고 그대로 짓는다 — 테스트가
    응답 전체를 고정한다. 기업 컨텍스트는 면접관의 것이다. 직무는 컨텍스트의 직무이고,
    JD 설명은 JD 로 분류한 문서 본문과 인재상이다. 사내 문서는 넣지 않는다.
    """
    session = store.get_session(session_id)
    if session is None:
        raise ApiError(ErrorCode.SESSION_NOT_FOUND, 404, "Session 을 찾을 수 없습니다.")
    interview = store.get_interview(session.interview_id)
    assert interview is not None  # session.interview_id 는 외래키다

    context = store.ensure_context(Context(owner_id=interview.interviewer_id))
    jd_texts = [
        store.get_doc_text(context.id, doc.id)
        for doc in store.list_docs(context.id)
        if doc.category is DocCategory.JD
    ]
    resume = store.get_resume(interview.id)
    prep = store.get_prep(interview.id) or InterviewPrep(interview_id=interview.id)

    return {
        "sessionId": session.id,
        "company": {"companyId": context.id, "name": context.company, "culture": None},
        "jobDescription": {
            "jdId": context.id,
            "companyId": context.id,
            "title": context.role,
            "description": "\n\n".join(
                text for text in [*jd_texts, context.talent_profile] if text
            ),
        },
        "competencies": prep.competencies,
        # 평가 기준은 항상 null 이다 — 점수 · 합격 판단을 만들지 않는다.
        "rubric": None,
        "candidate": {
            "candidateId": interview.id,
            "name": interview.candidate_name or "",
        },
        "resume": None
        if resume is None
        else {
            "resumeId": resume.id,
            "candidateId": interview.id,
            # 원본은 BE 가 들고 있고 AI 는 바이트를 받지 않는다 (#137 3장).
            "storageKey": None,
            # 못 뽑았으면 null 이다. 빈 이력서와 다른 사실이다.
            "text": store.get_resume_text(interview.id),
        },
        "resumeClaims": prep.resume_claims,
        # AI `Utterance` 의 필수 필드. 저장된 것은 전부 FINAL 이라 `passType` 은 뺀다.
        "utterances": [
            {
                "utteranceId": u.utterance_id,
                "sessionId": u.session_id,
                "trackId": u.track_id,
                "speaker": u.speaker.value,
                "seq": u.seq,
                "startMs": u.started_at_ms,
                "endMs": u.ended_at_ms,
                "content": u.text,
            }
            for u in store.list_utterances(session.id)
        ],
    }


@router.put("/interviews/{interviewId}/prep", status_code=status.HTTP_204_NO_CONTENT)
def put_prep(interview_id: InterviewIdPath, body: PrepUpsert, store: StoreDep) -> None:
    """`completed` · `partial` · `empty` 는 READY, `failed` 는 FAILED 다.

    `empty` 는 JD 본문이 없었다는 뜻이라 실패가 아니라 빈 목록이다. READY 는 FAILED 로
    되돌리지 않는다 (#132 와 같은 규칙).
    """
    done = body.status != "failed"
    prep = InterviewPrep(
        interview_id=interview_id,
        status=SummaryStatus.READY if done else SummaryStatus.FAILED,
        competencies=[c.model_dump(by_alias=True) for c in body.competencies]
        if done
        else [],
        resume_claims=[c.model_dump(by_alias=True) for c in body.resume_claims]
        if done
        else [],
        model=body.model if done else "",
        requested_at=body.requested_at,
        completed_at=utcnow(),
    )
    # 판정은 저장소가 한 문장으로 한다. 못 썼을 때만 다시 읽어 이유를 가린다.
    written = store.finish_prep(prep)
    if not written:
        stored = store.get_prep(interview_id)
        if stored is None:
            raise ApiError(
                ErrorCode.INTERVIEW_NOT_FOUND, 404, "면접 전 분석 자리가 없습니다."
            )
        if stored.requested_at != body.requested_at:
            # 이력서를 다시 올리는 사이 늦게 온 옛 결과다. 폴러는 다음 조회에서 새
            # 작업을 받는다. 공개 API 가 아니라 공개 명세의 ErrorCode 에 넣지 않는다.
            raise ApiError("PREP_OUTDATED", 409, "더 새로운 요청이 있습니다.")
        # 같은 요청의 실패 보고가 READY 를 덮지 않은 것이다.

    # 역량 · 주장 본문은 남기지 않는다. 주장은 지원자 이력서의 문장이다.
    logger.info(
        "면접 전 분석 수신 interview_id=%s agent_status=%s → %s 역량=%d개 주장=%d개",
        interview_id,
        body.status,
        prep.status.value if written else "그대로",
        len(prep.competencies),
        len(prep.resume_claims),
    )
