"""AI 분석 작업 — 할 일 조회 · 컨텍스트 · 면접 전 결과 (#162, #137 2-2 ~ 2-4).

AI 폴러가 N초마다 할 일을 묻고, 받은 작업의 컨텍스트를 읽어 분석한 뒤 결과를 써
넣는다. 한 번에 하나라 따로 큐를 두지 않는다 — 「할 일이 있다」는 사실이 DB 의
PROCESSING 행이다.

    GET  /jobs/pending                    → {kind, sessionId, interviewId,
                                            requestedAt} 또는 null
    GET  /sessions/{sessionId}/context    → InterviewContext + 이력서 본문 + 전사
    PUT  /interviews/{interviewId}/prep   → 204
    GET  /interviews/{interviewId}/report/context
                                          → 요약 + 역량(상태 포함) + 채택한 근거
    PUT  /interviews/{interviewId}/report → 204

내주는 순서는 **PREP → REVIEW → REPORT** 다. 면접 전 분석이 먼저다 — 다음 면접의
꼬리질문이 그걸 기다린다. 면접 후 분석(REVIEW, #164)은 면접이 끝나고 전사가 다
들어온 뒤에 나간다 — Agent 가 전사 WebSocket 을 1000 으로 닫았거나, 그 신호 없이
`TRANSCRIPT_GRACE` 가 지난 것이다. 결과는 `PUT /sessions/{sessionId}/review`
(`reviews.py`) 로 온다. 리포트(REPORT, #238)가 마지막이다 — 면접관이 버튼을 누르고
기다리는 일이지만, 앞의 둘은 **다음 면접**과 **검토 화면 전체**가 막혀 있다.

**재시도는 따로 없다.** 폴러가 죽으면 행이 PROCESSING 으로 남아 다음 조회에서 다시
나가고, 한도를 넘기면 FAILED 로 빠진다. FAILED 는 그 면접의 세션을 다시 만들거나
이력서를 다시 올리면 다시 요청된다. 면접 전 분석이 없거나 실패해도 면접은 진행된다
— 꼬리질문이 역량 · 주장 없이 만들어질 뿐이다 (#137 3장).
"""

import logging
from dataclasses import replace
from datetime import timedelta
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import StoreDep
from app.api.internal.deps import require_internal_auth
from app.api.internal.schemas import PendingJob, PrepUpsert, ReportUpsert
from app.core.config import settings
from app.core.errors import ApiError, ErrorCode
from app.domain.models import (
    Context,
    DocCategory,
    InterviewPrep,
    Job,
    SessionSummary,
    SummaryStatus,
    utcnow,
)
from app.services.report import adopted_findings, context_competencies

logger = logging.getLogger(__name__)

# 클라이언트용 API 가 아니다. 공개 명세에 실으면 FE 가 부를 것처럼 읽힌다.
router = APIRouter(
    dependencies=[Depends(require_internal_auth)], include_in_schema=False
)

SessionIdPath = Annotated[str, Path(alias="sessionId")]
InterviewIdPath = Annotated[str, Path(alias="interviewId")]

#: 면접 종료 뒤 전사 종료 신호를 기다리는 시간. Agent 가 1000 으로 닫지 못하고
#: 죽었어도 이만큼 지나면 받은 전사로 REVIEW 를 내준다.
TRANSCRIPT_GRACE: Final = timedelta(seconds=60)

#: 리포트를 보여 줄 수 있는 Agent 상태 (#238). `reviews.SHOWABLE` 과 지금은 같은 두
#: 값이지만 상수를 공유하지 않는다 — 검토 화면은 AI 가 낸 근거 전부를 보이고 리포트는
#: 면접관이 채택한 것만 본다. 보여 줄 기준이 갈라질 때 공용 상수를 건드리게 하면
#: 양쪽이 같이 바뀐다.
REPORT_SHOWABLE: Final = frozenset({"completed", "partial"})


@router.get("/jobs/pending", response_model=PendingJob | None)
def pending_job(store: StoreDep) -> Job | None:
    # 한도는 요약 한도에 추출 한도를 더한다. 이력서 · JD 추출을 기다리는 동안에도
    # 요청 시각부터 시계가 가므로, 요약 한도만 주면 추출이 늦은 면접은 내주기도
    # 전에 FAILED 가 된다.
    #
    # `Job` 을 그대로 돌려주면 FastAPI 가 `PendingJob` 으로 옮겨 camelCase 로 낸다.
    #
    # PREP 이 먼저다. 다음 면접의 꼬리질문이 그걸 기다린다 — 끝난 면접의 리뷰는
    # 조금 늦어도 된다.
    prep = store.next_prep(
        settings.summary_timeout + settings.doc_parse_timeout,
        settings.doc_parse_timeout,
    )
    if prep is not None:
        return prep
    review = store.next_review(settings.summary_timeout, TRANSCRIPT_GRACE)
    if review is not None:
        return review
    # 리포트가 마지막이다 (#238). 면접관이 버튼을 누르고 기다리는 일이지만, 앞의
    # 둘은 다음 면접과 검토 화면 전체가 막혀 있다.
    return store.next_report(settings.report_timeout)


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


@router.get("/interviews/{interviewId}/report/context")
def get_report_context(
    interview_id: InterviewIdPath, store: StoreDep
) -> dict[str, Any]:
    """리포트를 쓰는 데 필요한 것만 (#238). 요약 · 역량 · **채택한** 근거.

    세션 컨텍스트(`/sessions/{sessionId}/context`)를 쓰지 않는다. 저쪽은 전사와
    이력서 본문까지 통째로 주는데, 리포트는 **면접관이 채택한 근거**만으로 쓰는
    문서라 그걸 넘기면 채택하지 않은 것까지 글에 섞인다.

    **면접관 메모는 넣지 않는다.** 메모는 사람의 판단이고 리포트 맨 위 칸에 그대로
    나간다 — AI 가 그걸 읽고 다시 쓰면 누구의 말인지가 섞인다.

    기준 세션은 리포트에 박혀 있는 것을 쓴다. 그 사이 세션이 하나 더 끝나도 이미
    요청된 리포트의 근거는 흔들리지 않는다.
    """
    report = store.get_report(interview_id)
    if report is None:
        raise ApiError(ErrorCode.INTERVIEW_NOT_FOUND, 404, "리포트 자리가 없습니다.")

    # 요약 자리가 비어 있어도(옛 세션) 역량 목록은 나가야 한다. 채택한 근거가
    # 없으면 상태가 전부 MISSING 이고, AI 는 쓸 게 없다고 답하면 된다.
    summary = store.get_summary(report.session_id) or SessionSummary(
        session_id=report.session_id
    )
    adopted = adopted_findings(summary, store.list_marks(report.session_id))
    prep = store.get_prep(interview_id)
    return {
        "interviewId": interview_id,
        "sessionId": report.session_id,
        "requestedAt": report.requested_at,
        "summary": {"overview": summary.overview, "keyPoints": summary.key_points},
        # JD 역량 전부와 그 순서. AI 는 이 id 로만 카드를 돌려준다. `state` 는
        # 채택한 근거만 센 것이라 검토 화면의 coverage 와 다를 수 있다.
        "competencies": context_competencies(prep, adopted),
        # AI 가 보낸 모양 그대로다. 반려 · 미채택은 애초에 없다.
        "findings": adopted,
    }


@router.put("/interviews/{interviewId}/report", status_code=status.HTTP_204_NO_CONTENT)
def put_report(
    interview_id: InterviewIdPath, body: ReportUpsert, store: StoreDep
) -> None:
    """리포트 본문을 받는다 (#238). Agent 의 네 값을 화면의 두 값으로 줄이는 곳이다.

        completed · partial → READY
        empty               → FAILED + NO_EVIDENCE  (채택한 근거로 쓸 게 없었다)
        failed              → FAILED + null         (그 밖의 실패)

    `empty` 와 `failed` 를 가르는 이유는 면접관에게 다르게 말해야 하기 때문이다 —
    앞은 「채택한 근거로 만들 수 없었다」, 뒤는 「다시 만들어 보세요」다.

    기준 세션은 건드리지 않는다. 이미 열려 있는 자리에 본문만 채운다 — 그래서 먼저
    읽고 `replace` 로 덮는다. 자리가 없으면 404 다 (면접관이 누른 적이 없다).
    """
    stored = store.get_report(interview_id)
    if stored is None:
        raise ApiError(ErrorCode.INTERVIEW_NOT_FOUND, 404, "리포트 자리가 없습니다.")

    showable = body.status in REPORT_SHOWABLE
    report = replace(
        stored,
        status=SummaryStatus.READY if showable else SummaryStatus.FAILED,
        overview=body.overview if showable else "",
        competencies=[c.model_dump(by_alias=True) for c in body.competencies]
        if showable
        else [],
        failure_reason="NO_EVIDENCE" if body.status == "empty" else None,
        model=body.model if showable else "",
        requested_at=body.requested_at,
        completed_at=utcnow(),
    )
    # 판정은 저장소가 한 문장으로 한다. 못 썼을 때만 다시 읽어 이유를 가린다
    # (`put_prep` 과 같은 결).
    written = store.finish_report(report)
    if not written:
        fresh = store.get_report(interview_id)
        if fresh is None:
            raise ApiError(
                ErrorCode.INTERVIEW_NOT_FOUND, 404, "리포트 자리가 없습니다."
            )
        if fresh.requested_at != body.requested_at:
            # 면접관이 그 사이 다시 누른 것이다. 폴러는 다음 조회에서 새 작업을
            # 받는다. 공개 API 가 아니라 공개 명세의 ErrorCode 에 넣지 않는다.
            raise ApiError("REPORT_OUTDATED", 409, "더 새로운 요청이 있습니다.")
        # 같은 요청의 실패 보고가 READY 를 덮지 않은 것이다.

    # 본문은 남기지 않는다. 지원자 발화와 지원서 문장이 들어 있다.
    logger.info(
        "리포트 수신 interview_id=%s agent_status=%s → %s 역량=%d개 문장=%d개",
        interview_id,
        body.status,
        report.status.value if written else "그대로",
        len(report.competencies),
        sum(
            len(c.confirmed) + len(c.unconfirmed) + len(c.next_questions)
            for c in body.competencies
        ),
    )


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
