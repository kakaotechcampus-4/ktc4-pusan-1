"""저장소 인터페이스와 인메모리 구현.

라우터는 이 Protocol 에만 의존한다. 실제 구현은 `app/infra/postgres.py` 이고,
테스트와 로컬 기동은 아래 인메모리 구현을 그대로 쓴다.

⚠️ `save_session` 을 반드시 불러야 한다. 인메모리 구현은 객체를 참조로 돌려주므로
상태를 바꾸면 저장소에도 반영되지만, DB 구현은 그렇지 않다. 저장을 빠뜨리면
응답은 정상인데 재조회하면 이전 상태가 나오는 식으로 조용히 깨진다.
"""

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Protocol

from app.domain.models import (
    Context,
    ContextDoc,
    DocCategory,
    DocStatus,
    FindingState,
    Interview,
    InterviewPrep,
    Job,
    JobKind,
    Resume,
    ReviewMark,
    ReviewStatus,
    Role,
    Session,
    SessionStatus,
    SessionSummary,
    Suggestion,
    SummaryStatus,
    TranscriptStage,
    User,
    Utterance,
    utcnow,
)


class Store(Protocol):
    def add_interview(self, interview: Interview) -> None: ...

    def get_interview(self, interview_id: str) -> Interview | None: ...

    def list_interviews(
        self, interviewer_id: str
    ) -> list[tuple[Interview, Session | None, SummaryStatus | None]]:
        """그 면접관의 면접을 최신순으로, 마지막으로 끝난 세션과 그 요약 상태와 함께.

        끝난 세션이 없는 면접은 둘 다 None 이다 (#137 1-1).
        """
        ...

    def update_review(
        self, interview_id: str, status: ReviewStatus | None, memo: str | None
    ) -> Interview | None:
        """면접관의 검토를 받고 **저장된 면접**을 돌려준다. None 은 그대로 둔다.

        규칙은 `Interview.update_review` 와 같다. 판정과 갱신은 한 문장이다 — 읽은
        객체를 통째로 덮어쓰면, 메모만 보낸 요청과 확정만 보낸 요청이 겹칠 때 보내지
        않은 값이 읽어 둔 옛 값으로 돌아간다. 없는 면접이면 None.
        """
        ...

    def last_ended_session(self, interview_id: str) -> Session | None:
        """그 면접에서 가장 나중에 끝난 세션. 검토 화면의 기준 세션이다 (#163).

        목록(`list_interviews`)이 붙이는 세션과 같은 것이어야 목록과 상세가 어긋나지
        않는다. 끝난 세션이 없으면 None.
        """
        ...

    def add_session(self, session: Session) -> None: ...

    def get_session(self, session_id: str) -> Session | None: ...

    def save_session(
        self, session: Session, *, expected_status: SessionStatus | None = None
    ) -> bool:
        """변경된 Session 을 저장한다. 상태 전이 뒤에는 항상 부른다.

        `expected_status` 를 주면 저장소에 남아 있는 상태가 그 값일 때만 쓰고,
        아니면 아무것도 안 쓰고 False 를 돌려준다. 부른 쪽이 409 로 바꾼다.

        `None` 이면 조건 없이 쓴다. 경쟁이 없는 자리에만 쓴다.

        전사 원점(`transcript_origin_at`)은 쓰지 않는다 — `mark_origin` 만 쓴다.
        """
        ...

    def mark_origin(self, session_id: str, at: datetime) -> bool:
        """전사 원점(t=0)을 기록한다. 이미 있으면 더 이른 쪽만 남긴다 (#86).

        읽고-고쳐-쓰기가 아니라 저장소가 한 번에 판단한다. 그래서 webhook 이
        재전송되거나 순서가 뒤바뀌어 와도, 시작 · 종료 저장과 겹쳐도 서로를
        덮어쓰지 않는다. 값이 바뀌었으면 True, 세션이 없거나 더 이른 값이
        이미 있으면 False.
        """
        ...

    # ── 기업 컨텍스트 ───────────────────────────────────

    def ensure_context(self, context: Context) -> Context:
        """주인당 하나. 이미 있으면 **그것을 돌려주고 새 것은 버린다.**

        확인한 뒤 넣는 두 단계로 나누면 그 사이에 다른 요청이 넣을 수 있다. 설정
        화면에 들어올 때마다 부르는 자리라 실제로 겹친다 — 한 문장으로 끝내야 한다.
        """
        ...

    def get_context(self, context_id: str) -> Context | None: ...

    def save_context(self, context: Context) -> None: ...

    def add_doc(self, doc: ContextDoc, content: bytes) -> None:
        """문서 메타데이터와 원본을 같이 넣는다."""
        ...

    def list_docs(self, context_id: str) -> list[ContextDoc]:
        """올린 순서대로."""
        ...

    def get_doc(self, context_id: str, doc_id: str) -> ContextDoc | None: ...

    def delete_doc(self, context_id: str, doc_id: str) -> bool:
        """지웠으면 True. 없던 문서면 False."""
        ...

    def finish_doc(self, context_id: str, doc_id: str, text: str | None) -> None:
        """추출 결과를 받는다. 본문이 있으면 READY, None·빈 문자열이면 FAILED.

        그 사이 문서가 지워졌으면 아무것도 하지 않는다.
        """
        ...

    def get_doc_text(self, context_id: str, doc_id: str) -> str | None:
        """뽑아 둔 본문. 아직 없거나 못 뽑았으면 None. 목록 조회에는 싣지 않는다."""
        ...

    # ── 지원자 이력서 ───────────────────────────────────

    def save_resume(self, resume: Resume, content: bytes) -> None:
        """면접 한 건에 한 장. 이미 있으면 덮어쓴다."""
        ...

    def get_resume(self, interview_id: str) -> Resume | None: ...

    def finish_resume(
        self, interview_id: str, resume_id: str, text: str | None
    ) -> None:
        """`finish_doc` 과 같다. 추출 도중 다시 올라와 id 가 바뀌었으면 버린다."""
        ...

    def get_resume_text(self, interview_id: str) -> str | None: ...

    def ensure_summary(self, summary: SessionSummary) -> SessionSummary:
        """요약 자리를 만들고 돌려준다. 이미 있으면 **있는 것을 돌려준다.**

        면접 종료를 두 번 눌러도, 종료 요청이 겹쳐 들어와도 기다리기 시작한
        시각이 뒤로 밀리면 안 된다. 밀리면 한도가 계속 연장돼 FAILED 로 가지
        못한다.
        """
        ...

    def get_summary(self, session_id: str) -> SessionSummary | None: ...

    def save_summary(self, summary: SessionSummary) -> None:
        """Agent 가 만든 결과를 받아 둔다. 조건 없이 덮어쓴다."""
        ...

    def fail_summary(self, session_id: str) -> bool:
        """Agent 의 실패 보고. READY 가 아니면 FAILED 로 넘기고 본문을 비운다.

        READY 면 아무것도 바꾸지 않고 False 다. Agent 의 재시도 · 재실행에서 실패
        한 번이 이미 성공한 요약을 지우면 안 된다 (#132). 판정과 갱신은 한 문장이다
        — 읽고 나서 쓰면 그 사이에 들어온 READY 를 덮는다.
        """
        ...

    def expire_summary(
        self, session_id: str, limit: timedelta
    ) -> SessionSummary | None:
        """한도를 넘긴 요약을 FAILED 로 넘기고 **최종 상태**를 돌려준다.

        판정·전이·저장을 한 군데서 끝낸다. 라우터가 읽고 판정하고 쓰면 그 사이가
        열려서, 한도가 막 지나는 순간에 들어온 Agent 의 결과를 덮어 지운다 (#115).

        한도를 안 넘겼거나 이미 끝난 요약이면 아무것도 바꾸지 않고 지금 값을
        그대로 돌려준다. 요약 자리가 없으면 None.

        한도를 인자로 받는다 — 저장소는 설정을 읽지 않는다.
        """
        ...

    # ── 면접 전 분석 (#162) ─────────────────────────────────

    def ensure_prep(self, prep: InterviewPrep) -> None:
        """면접 전 분석 자리를 연다. 이미 있으면 **그대로 둔다** — FAILED 만 다시 연다.

        세션을 만들 때 부른다. 세션을 또 만들어도 요청 시각이 밀리지 않아야 한도가
        연장되지 않는다 — `ensure_summary` 와 같은 이유다. FAILED 는 다시 연다. 폴러가
        한도 넘게 멈춰 실패한 면접을 이력서 재업로드 말고도 되살릴 길이다.
        """
        ...

    def restart_prep(self, interview_id: str) -> None:
        """이력서가 바뀌었다. 자리를 비우고 새 요청 시각으로 다시 PROCESSING 으로 연다.

        자리가 없으면 아무것도 하지 않는다. FE 는 세션보다 이력서를 먼저 올리는데,
        세션이 없으면 AI 가 읽을 컨텍스트도 없다 — 자리는 세션을 만들 때 연다.

        면접이 끝났으면(끝난 세션이 있으면) 아무것도 하지 않는다(#163). 검토 중에
        역량 · 주장이 비면 상세의 coverage · 근거가 사라진다. 「끝났는가」는 같은
        문장에서 본다 — 종료와 이력서 업로드가 겹쳐도 뚫리지 않게.
        """
        ...

    def get_prep(self, interview_id: str) -> InterviewPrep | None: ...

    def finish_prep(self, prep: InterviewPrep) -> bool:
        """AI 의 결과를 받는다. 썼으면 True.

        저장된 요청 시각이 `prep.requested_at` 과 같을 때만 쓴다. 다르면 이력서를
        다시 올리는 사이 늦게 온 옛 결과다. FAILED 는 READY 를 덮지 않는다 (#132).
        판정과 갱신은 한 문장이다.
        """
        ...

    def next_prep(self, limit: timedelta, parse_limit: timedelta) -> Job | None:
        """AI 폴러에게 내줄 PREP 하나. 요청이 오래된 것부터, 없으면 None.

        먼저 한도(`limit`)를 넘긴 PROCESSING 을 FAILED 로 넘긴다. 폴러가 죽어 결과가
        안 오는 작업이 큐를 영원히 막지 않게 한다.

        그 면접의 이력서나 면접관의 JD 문서가 아직 본문을 뽑는 중이면 건너뛴다 — 빈
        이력서로 분석하면 주장이 비어 버린다. 추출이 `parse_limit` 을 넘겨 멈춘 문서는
        화면과 같이 실패로 보고 기다리지 않는다.

        세션은 그 면접의 가장 최근 것을 싣는다. 컨텍스트를 세션으로 읽기 때문이다.
        """
        ...

    # ── 검토 표시 (#163) ─────────────────────────────────

    def update_mark(
        self,
        session_id: str,
        item_id: str,
        *,
        state: FindingState | None = None,
        bookmarked: bool | None = None,
    ) -> ReviewMark:
        """채택 · 북마크를 바꾸고 **저장된 표시**를 돌려준다. None 은 그대로 둔다.

        한 문장 UPSERT 다. 채택과 북마크를 따로 보내는 요청이 겹쳐도 서로를 지우지
        않는다. 행이 없으면 「제안됨 · 북마크 없음」에서 시작한다.
        """
        ...

    def list_marks(self, session_id: str) -> list[ReviewMark]:
        """그 세션의 표시 전부. 순서는 정하지 않는다 — 부르는 쪽이 id 로 찾는다."""
        ...

    # ── 사용자 ──────────────────────────────────────────

    def upsert_user(self, user: User) -> User:
        """카카오 계정으로 찾아 넣거나 갱신하고 **저장된 사용자**를 돌려준다.

        이미 있으면 닉네임·프로필만 새 값으로 바꾸고 id 는 처음 것을 지킨다 —
        id 가 바뀌면 그 사람이 만든 면접을 잃는다. 첫 로그인이 동시에 두 번
        들어와도 한 명만 생겨야 해서 한 문장으로 끝낸다.
        """
        ...

    def get_user(self, user_id: str) -> User | None: ...

    # ── 전사·꼬리질문 (#85) ─────────────────────────────────

    def upsert_utterance(self, utterance: Utterance) -> None:
        """같은 `(session, stage, utterance_id)` 면 덮어쓴다. 교정본이 이 길로 온다.

        Agent 는 ACK 를 받아야 버퍼에서 지운다 (#76). 여기가 끝나야 ACK 가 나간다.
        """
        ...

    def list_utterances(
        self, session_id: str, stage: TranscriptStage = TranscriptStage.LIVE
    ) -> list[Utterance]:
        """말한 순서대로. 같은 ms 에 시작했으면 면접관이 먼저, 그다음 id 순이다.

        질문이 같은 순간의 답보다 앞에 와야 Q&A 로 읽힌다. `seq` 는 PR #158 부터
        오지만 그 전에 받은 발화는 비어 있어 순서는 여기서 정한다.
        """
        ...

    def add_suggestion(self, suggestion: Suggestion) -> None:
        """이미 같은 id 가 있으면 **처음 것을 남긴다.**

        Agent 의 재시도가 이 길로 온다.
        """
        ...

    def list_suggestions(self, session_id: str) -> list[Suggestion]:
        """도착한 순서대로."""
        ...


class InMemoryStore:
    """DB 구현과 같은 계약을 주는 인메모리 저장소.

    ⚠️ `get_*` 은 **복사본**을 돌려준다. 참조를 돌려주면 호출자가 손에 든 객체와
    저장소가 같은 것이 되어, 라우터가 저장을 빼먹어도 여기서는 통과한다. 그러면
    인메모리로 도는 테스트가 DB 에서만 나는 버그를 못 잡는다 (#115 가 그 경우였다).
    복사본을 주면 「저장했는가」가 여기서도 드러난다.
    """

    def __init__(self) -> None:
        self._interviews: dict[str, Interview] = {}
        self._sessions: dict[str, Session] = {}
        self._contexts: dict[str, Context] = {}
        #: (context_id, doc_id) -> (메타데이터, 원본)
        self._docs: dict[tuple[str, str], tuple[ContextDoc, bytes]] = {}
        #: interview_id -> (메타데이터, 원본)
        self._resumes: dict[str, tuple[Resume, bytes]] = {}
        #: 뽑은 본문. 문서는 (context_id, doc_id), 이력서는 interview_id 가 키다.
        self._texts: dict[object, str] = {}

        self._summaries: dict[str, SessionSummary] = {}
        #: interview_id -> 면접 전 분석
        self._preps: dict[str, InterviewPrep] = {}
        #: (session_id, item_id) -> 채택 · 북마크
        self._marks: dict[tuple[str, str], ReviewMark] = {}
        self._users: dict[str, User] = {}

        #: (session_id, stage, utterance_id) -> 발화
        self._utterances: dict[tuple[str, TranscriptStage, str], Utterance] = {}
        #: (session_id, suggestion_id) -> 꼬리질문
        self._suggestions: dict[tuple[str, str], Suggestion] = {}

    def add_interview(self, interview: Interview) -> None:
        self._interviews[interview.id] = deepcopy(interview)

    def get_interview(self, interview_id: str) -> Interview | None:
        found = self._interviews.get(interview_id)
        return None if found is None else deepcopy(found)

    def list_interviews(
        self, interviewer_id: str
    ) -> list[tuple[Interview, Session | None, SummaryStatus | None]]:
        mine = sorted(
            (
                i
                for i in self._interviews.values()
                if i.interviewer_id == interviewer_id
            ),
            key=lambda i: i.created_at,
            reverse=True,
        )
        listed: list[tuple[Interview, Session | None, SummaryStatus | None]] = []
        for interview in mine:
            session = self.last_ended_session(interview.id)
            summary = None if session is None else self._summaries.get(session.id)
            listed.append(
                (
                    deepcopy(interview),
                    session,
                    None if summary is None else summary.status,
                )
            )
        return listed

    def update_review(
        self, interview_id: str, status: ReviewStatus | None, memo: str | None
    ) -> Interview | None:
        stored = self._interviews.get(interview_id)
        if stored is None:
            return None
        stored.update_review(status, memo)
        return deepcopy(stored)

    def last_ended_session(self, interview_id: str) -> Session | None:
        ended = [
            s
            for s in self._sessions.values()
            if s.interview_id == interview_id and s.ended_at is not None
        ]
        last = max(ended, key=lambda s: s.ended_at or s.created_at, default=None)
        return None if last is None else deepcopy(last)

    def add_session(self, session: Session) -> None:
        self._sessions[session.id] = deepcopy(session)

    def get_session(self, session_id: str) -> Session | None:
        found = self._sessions.get(session_id)
        return None if found is None else deepcopy(found)

    def save_session(
        self, session: Session, *, expected_status: SessionStatus | None = None
    ) -> bool:
        # 없는 세션은 쓰지 않는다. DB 구현의 UPDATE 가 0행을 바꾸는 것과 같다 —
        # `save_session` 은 갱신이지 추가가 아니다 (추가는 `add_session`).
        stored = self._sessions.get(session.id)
        if stored is None:
            return False
        if expected_status is not None and stored.status is not expected_status:
            return False
        saved = deepcopy(session)
        # 원점은 mark_origin 만 쓴다. 들고 온 객체의 값이 낡았어도 덮어쓰지 않는다.
        saved.transcript_origin_at = stored.transcript_origin_at
        self._sessions[session.id] = saved
        return True

    def mark_origin(self, session_id: str, at: datetime) -> bool:
        stored = self._sessions.get(session_id)
        if stored is None:
            return False
        origin = stored.transcript_origin_at
        if origin is not None and origin <= at:
            return False
        stored.transcript_origin_at = at
        return True

    # ── 기업 컨텍스트 ───────────────────────────────────

    def ensure_context(self, context: Context) -> Context:
        for existing in self._contexts.values():
            if existing.owner_id == context.owner_id:
                return existing
        self._contexts[context.id] = context
        return context

    def get_context(self, context_id: str) -> Context | None:
        found = self._contexts.get(context_id)
        return None if found is None else deepcopy(found)

    def save_context(self, context: Context) -> None:
        self._contexts[context.id] = context

    def add_doc(self, doc: ContextDoc, content: bytes) -> None:
        self._docs[(doc.context_id, doc.id)] = (deepcopy(doc), content)

    def list_docs(self, context_id: str) -> list[ContextDoc]:
        return [
            deepcopy(doc)
            for (ctx_id, _), (doc, _content) in self._docs.items()
            if ctx_id == context_id
        ]

    def get_doc(self, context_id: str, doc_id: str) -> ContextDoc | None:
        found = self._docs.get((context_id, doc_id))
        return None if found is None else deepcopy(found[0])

    def delete_doc(self, context_id: str, doc_id: str) -> bool:
        self._texts.pop((context_id, doc_id), None)
        return self._docs.pop((context_id, doc_id), None) is not None

    def finish_doc(self, context_id: str, doc_id: str, text: str | None) -> None:
        found = self._docs.get((context_id, doc_id))
        if found is None:
            return
        found[0].status = DocStatus.READY if text else DocStatus.FAILED
        self._set_text((context_id, doc_id), text)

    def get_doc_text(self, context_id: str, doc_id: str) -> str | None:
        return self._texts.get((context_id, doc_id))

    def _set_text(self, key: object, text: str | None) -> None:
        if text:
            self._texts[key] = text
        else:
            self._texts.pop(key, None)

    # ── 지원자 이력서 ───────────────────────────────────

    def save_resume(self, resume: Resume, content: bytes) -> None:
        self._resumes[resume.interview_id] = (deepcopy(resume), content)
        self._texts.pop(resume.interview_id, None)

    def finish_resume(
        self, interview_id: str, resume_id: str, text: str | None
    ) -> None:
        found = self._resumes.get(interview_id)
        if found is None or found[0].id != resume_id:
            return
        found[0].status = DocStatus.READY if text else DocStatus.FAILED
        self._set_text(interview_id, text)

    def get_resume_text(self, interview_id: str) -> str | None:
        return self._texts.get(interview_id)

    def get_resume(self, interview_id: str) -> Resume | None:
        found = self._resumes.get(interview_id)
        return None if found is None else deepcopy(found[0])

    def ensure_summary(self, summary: SessionSummary) -> SessionSummary:
        kept = self._summaries.setdefault(summary.session_id, deepcopy(summary))
        return deepcopy(kept)

    def get_summary(self, session_id: str) -> SessionSummary | None:
        found = self._summaries.get(session_id)
        return None if found is None else deepcopy(found)

    def save_summary(self, summary: SessionSummary) -> None:
        stored = self._summaries.get(summary.session_id)
        if stored is None:
            return
        # `requested_at` 은 저장소가 들고 있던 것을 지킨다 — 한도의 기준점이라
        # 호출자가 덮으면 마감이 밀린다. DB 구현의 UPDATE 도 이 컬럼을 뺀다.
        fresh = deepcopy(summary)
        fresh.requested_at = stored.requested_at
        self._summaries[summary.session_id] = fresh

    def fail_summary(self, session_id: str) -> bool:
        stored = self._summaries.get(session_id)
        if stored is None or stored.status is SummaryStatus.READY:
            return False
        stored.give_up()
        return True

    def expire_summary(
        self, session_id: str, limit: timedelta
    ) -> SessionSummary | None:
        stored = self._summaries.get(session_id)
        if stored is None:
            return None
        if stored.overdue(limit):
            stored.give_up()
        return deepcopy(stored)

    # ── 면접 전 분석 (#162) ─────────────────────────────────

    def ensure_prep(self, prep: InterviewPrep) -> None:
        stored = self._preps.get(prep.interview_id)
        if stored is None or stored.status is SummaryStatus.FAILED:
            self._preps[prep.interview_id] = deepcopy(prep)

    def restart_prep(self, interview_id: str) -> None:
        if (
            interview_id in self._preps
            and self.last_ended_session(interview_id) is None
        ):
            self._preps[interview_id] = InterviewPrep(interview_id=interview_id)

    def get_prep(self, interview_id: str) -> InterviewPrep | None:
        found = self._preps.get(interview_id)
        return None if found is None else deepcopy(found)

    def finish_prep(self, prep: InterviewPrep) -> bool:
        stored = self._preps.get(prep.interview_id)
        if stored is None or stored.requested_at != prep.requested_at:
            return False
        if prep.status is SummaryStatus.FAILED and stored.status is SummaryStatus.READY:
            return False
        self._preps[prep.interview_id] = deepcopy(prep)
        return True

    def next_prep(self, limit: timedelta, parse_limit: timedelta) -> Job | None:
        now = utcnow()
        waiting = [
            p for p in self._preps.values() if p.status is SummaryStatus.PROCESSING
        ]
        for prep in waiting:
            if now - prep.requested_at > limit:
                prep.status = SummaryStatus.FAILED
                prep.completed_at = now

        jobs: list[Job] = []
        for prep in waiting:
            session = self._latest_session(prep.interview_id)
            if (
                prep.status is SummaryStatus.PROCESSING
                and session is not None
                and not self._reading_inputs(prep.interview_id, parse_limit)
            ):
                jobs.append(
                    Job(JobKind.PREP, session.id, prep.interview_id, prep.requested_at)
                )
        return min(jobs, key=lambda j: j.requested_at, default=None)

    def _latest_session(self, interview_id: str) -> Session | None:
        mine = [s for s in self._sessions.values() if s.interview_id == interview_id]
        return max(mine, key=lambda s: s.created_at, default=None)

    def _reading_inputs(self, interview_id: str, parse_limit: timedelta) -> bool:
        """그 면접의 이력서나 면접관의 JD 가 아직 본문을 뽑는 중인가."""
        resume = self._resumes.get(interview_id)
        if resume and resume[0].shown_status(parse_limit) is DocStatus.PARSING:
            return True
        interviewer = self._interviews[interview_id].interviewer_id
        return any(
            doc.category is DocCategory.JD
            and doc.shown_status(parse_limit) is DocStatus.PARSING
            and self._contexts[doc.context_id].owner_id == interviewer
            for doc, _ in self._docs.values()
        )

    # ── 검토 표시 (#163) ─────────────────────────────────

    def update_mark(
        self,
        session_id: str,
        item_id: str,
        *,
        state: FindingState | None = None,
        bookmarked: bool | None = None,
    ) -> ReviewMark:
        mark = self._marks.setdefault(
            (session_id, item_id), ReviewMark(session_id=session_id, item_id=item_id)
        )
        if state is not None:
            mark.state = state
        if bookmarked is not None:
            mark.bookmarked = bookmarked
        return deepcopy(mark)

    def list_marks(self, session_id: str) -> list[ReviewMark]:
        return [deepcopy(m) for (sid, _), m in self._marks.items() if sid == session_id]

    # ── 사용자 ──────────────────────────────────────────

    def upsert_user(self, user: User) -> User:
        for stored in self._users.values():
            if stored.kakao_id == user.kakao_id:
                stored.nickname = user.nickname
                stored.profile_image_url = user.profile_image_url
                return deepcopy(stored)
        self._users[user.id] = deepcopy(user)
        return deepcopy(user)

    def get_user(self, user_id: str) -> User | None:
        found = self._users.get(user_id)
        return None if found is None else deepcopy(found)

    def upsert_utterance(self, utterance: Utterance) -> None:
        key = (utterance.session_id, utterance.stage, utterance.utterance_id)
        self._utterances[key] = deepcopy(utterance)

    def list_utterances(
        self, session_id: str, stage: TranscriptStage = TranscriptStage.LIVE
    ) -> list[Utterance]:
        found = [
            u
            for (sid, st, _), u in self._utterances.items()
            if sid == session_id and st == stage
        ]
        found.sort(
            key=lambda u: (
                u.started_at_ms,
                u.speaker is not Role.INTERVIEWER,
                u.utterance_id,
            )
        )
        return deepcopy(found)

    def add_suggestion(self, suggestion: Suggestion) -> None:
        key = (suggestion.session_id, suggestion.suggestion_id)
        self._suggestions.setdefault(key, deepcopy(suggestion))

    def list_suggestions(self, session_id: str) -> list[Suggestion]:
        found = [s for (sid, _), s in self._suggestions.items() if sid == session_id]
        found.sort(key=lambda s: (s.created_at, s.suggestion_id))
        return deepcopy(found)

    def clear(self) -> None:
        """테스트용."""
        self._interviews.clear()
        self._sessions.clear()

        self._contexts.clear()
        self._docs.clear()
        self._resumes.clear()
        self._texts.clear()

        self._summaries.clear()
        self._preps.clear()
        self._marks.clear()
        self._users.clear()

        self._utterances.clear()
        self._suggestions.clear()


store: Store = InMemoryStore()
