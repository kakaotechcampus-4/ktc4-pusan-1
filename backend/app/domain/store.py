"""저장소 인터페이스와 인메모리 구현.

라우터는 이 Protocol 에만 의존한다. 실제 구현은 `app/infra/postgres.py` 이고,
테스트와 로컬 기동은 아래 인메모리 구현을 그대로 쓴다.

⚠️ `save_session` 을 반드시 불러야 한다. 인메모리 구현은 객체를 참조로 돌려주므로
상태를 바꾸면 저장소에도 반영되지만, DB 구현은 그렇지 않다. 저장을 빠뜨리면
응답은 정상인데 재조회하면 이전 상태가 나오는 식으로 조용히 깨진다.
"""

from typing import Protocol

from app.domain.models import (
    Context,
    ContextDoc,
    Interview,
    Resume,
    Session,
    SessionSummary,
)


class Store(Protocol):
    def add_interview(self, interview: Interview) -> None: ...

    def get_interview(self, interview_id: str) -> Interview | None: ...

    def add_session(self, session: Session) -> None: ...

    def get_session(self, session_id: str) -> Session | None: ...

    def save_session(self, session: Session) -> None:
        """변경된 Session 을 저장한다. 상태 전이 뒤에는 항상 부른다."""
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

    # ── 지원자 이력서 ───────────────────────────────────

    def save_resume(self, resume: Resume, content: bytes) -> None:
        """면접 한 건에 한 장. 이미 있으면 덮어쓴다."""
        ...

    def get_resume(self, interview_id: str) -> Resume | None: ...

    def ensure_summary(self, summary: SessionSummary) -> SessionSummary:
        """요약 자리를 만들고 돌려준다. 이미 있으면 **있는 것을 돌려준다.**

        면접 종료를 두 번 눌러도, 종료 요청이 겹쳐 들어와도 기다리기 시작한
        시각이 뒤로 밀리면 안 된다. 밀리면 한도가 계속 연장돼 FAILED 로 가지
        못한다.
        """
        ...

    def get_summary(self, session_id: str) -> SessionSummary | None: ...

    def save_summary(self, summary: SessionSummary) -> None: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._interviews: dict[str, Interview] = {}
        self._sessions: dict[str, Session] = {}
        self._contexts: dict[str, Context] = {}
        #: (context_id, doc_id) -> (메타데이터, 원본)
        self._docs: dict[tuple[str, str], tuple[ContextDoc, bytes]] = {}
        #: interview_id -> (메타데이터, 원본)
        self._resumes: dict[str, tuple[Resume, bytes]] = {}

        self._summaries: dict[str, SessionSummary] = {}

    def add_interview(self, interview: Interview) -> None:
        self._interviews[interview.id] = interview

    def get_interview(self, interview_id: str) -> Interview | None:
        return self._interviews.get(interview_id)

    def add_session(self, session: Session) -> None:
        self._sessions[session.id] = session

    def get_session(self, session_id: str) -> Session | None:
        # 값을 그대로 돌려준다. 라우터가 상태를 바꾸면 저장소에도 반영된다.
        return self._sessions.get(session_id)

    def save_session(self, session: Session) -> None:
        # 참조가 이미 같은 객체라 사실상 no-op 이지만, 라우터가 DB 구현에서도
        # 똑같이 동작하도록 호출 규약을 맞춰 둔다.
        self._sessions[session.id] = session

    # ── 기업 컨텍스트 ───────────────────────────────────

    def ensure_context(self, context: Context) -> Context:
        for existing in self._contexts.values():
            if existing.owner_id == context.owner_id:
                return existing
        self._contexts[context.id] = context
        return context

    def get_context(self, context_id: str) -> Context | None:
        return self._contexts.get(context_id)

    def save_context(self, context: Context) -> None:
        self._contexts[context.id] = context

    def add_doc(self, doc: ContextDoc, content: bytes) -> None:
        self._docs[(doc.context_id, doc.id)] = (doc, content)

    def list_docs(self, context_id: str) -> list[ContextDoc]:
        return [
            doc
            for (ctx_id, _), (doc, _content) in self._docs.items()
            if ctx_id == context_id
        ]

    def get_doc(self, context_id: str, doc_id: str) -> ContextDoc | None:
        found = self._docs.get((context_id, doc_id))
        return None if found is None else found[0]

    def delete_doc(self, context_id: str, doc_id: str) -> bool:
        return self._docs.pop((context_id, doc_id), None) is not None

    # ── 지원자 이력서 ───────────────────────────────────

    def save_resume(self, resume: Resume, content: bytes) -> None:
        self._resumes[resume.interview_id] = (resume, content)

    def get_resume(self, interview_id: str) -> Resume | None:
        found = self._resumes.get(interview_id)
        return None if found is None else found[0]

    def ensure_summary(self, summary: SessionSummary) -> SessionSummary:
        return self._summaries.setdefault(summary.session_id, summary)

    def get_summary(self, session_id: str) -> SessionSummary | None:
        return self._summaries.get(session_id)

    def save_summary(self, summary: SessionSummary) -> None:
        self._summaries[summary.session_id] = summary

    def clear(self) -> None:
        """테스트용."""
        self._interviews.clear()
        self._sessions.clear()
        self._contexts.clear()
        self._docs.clear()
        self._resumes.clear()

        self._summaries.clear()


store: Store = InMemoryStore()
