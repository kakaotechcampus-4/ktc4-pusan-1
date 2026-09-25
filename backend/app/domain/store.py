"""저장소 인터페이스와 인메모리 구현.

라우터는 이 Protocol 에만 의존한다. 실제 구현은 `app/infra/postgres.py` 이고,
테스트와 로컬 기동은 아래 인메모리 구현을 그대로 쓴다.

⚠️ `save_session` 을 반드시 불러야 한다. 인메모리 구현은 객체를 참조로 돌려주므로
상태를 바꾸면 저장소에도 반영되지만, DB 구현은 그렇지 않다. 저장을 빠뜨리면
응답은 정상인데 재조회하면 이전 상태가 나오는 식으로 조용히 깨진다.
"""

from copy import deepcopy
from datetime import timedelta
from typing import Protocol

from app.domain.models import (
    Context,
    ContextDoc,
    Interview,
    Resume,
    Session,
    SessionStatus,
    SessionSummary,
)


class Store(Protocol):
    def add_interview(self, interview: Interview) -> None: ...

    def get_interview(self, interview_id: str) -> Interview | None: ...

    def add_session(self, session: Session) -> None: ...

    def get_session(self, session_id: str) -> Session | None: ...

    def save_session(
        self, session: Session, *, expected_status: SessionStatus | None = None
    ) -> bool:
        """변경된 Session 을 저장한다. 상태 전이 뒤에는 항상 부른다.

        `expected_status` 를 주면 저장소에 남아 있는 상태가 그 값일 때만 쓰고,
        아니면 아무것도 안 쓰고 False 를 돌려준다. 부른 쪽이 409 로 바꾼다.

        `None` 이면 조건 없이 쓴다. 경쟁이 없는 자리에만 쓴다.
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

    def save_summary(self, summary: SessionSummary) -> None:
        """Agent 가 만든 결과를 받아 둔다. 조건 없이 덮어쓴다."""
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

        self._summaries: dict[str, SessionSummary] = {}

    def add_interview(self, interview: Interview) -> None:
        self._interviews[interview.id] = interview

    def get_interview(self, interview_id: str) -> Interview | None:
        found = self._interviews.get(interview_id)
        return None if found is None else deepcopy(found)

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
        self._sessions[session.id] = deepcopy(session)
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
        self._docs[(doc.context_id, doc.id)] = (doc, content)

    def list_docs(self, context_id: str) -> list[ContextDoc]:
        return [
            doc
            for (ctx_id, _), (doc, _content) in self._docs.items()
            if ctx_id == context_id
        ]

    def get_doc(self, context_id: str, doc_id: str) -> ContextDoc | None:
        found = self._docs.get((context_id, doc_id))
        return None if found is None else deepcopy(found[0])

    def delete_doc(self, context_id: str, doc_id: str) -> bool:
        return self._docs.pop((context_id, doc_id), None) is not None

    # ── 지원자 이력서 ───────────────────────────────────

    def save_resume(self, resume: Resume, content: bytes) -> None:
        self._resumes[resume.interview_id] = (resume, content)

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

    def expire_summary(
        self, session_id: str, limit: timedelta
    ) -> SessionSummary | None:
        stored = self._summaries.get(session_id)
        if stored is None:
            return None
        if stored.overdue(limit):
            stored.give_up()
        return deepcopy(stored)

    def clear(self) -> None:
        """테스트용."""
        self._interviews.clear()
        self._sessions.clear()

        self._contexts.clear()
        self._docs.clear()
        self._resumes.clear()

        self._summaries.clear()


store: Store = InMemoryStore()
