"""저장소 인터페이스와 인메모리 구현.

라우터는 이 Protocol 에만 의존한다. 실제 구현은 `app/infra/postgres.py` 이고,
테스트와 로컬 기동은 아래 인메모리 구현을 그대로 쓴다.

⚠️ `save_session` 을 반드시 불러야 한다. 인메모리 구현은 객체를 참조로 돌려주므로
상태를 바꾸면 저장소에도 반영되지만, DB 구현은 그렇지 않다. 저장을 빠뜨리면
응답은 정상인데 재조회하면 이전 상태가 나오는 식으로 조용히 깨진다.
"""

from typing import Protocol

from app.domain.models import Interview, Session, SessionSummary


class Store(Protocol):
    def add_interview(self, interview: Interview) -> None: ...

    def get_interview(self, interview_id: str) -> Interview | None: ...

    def add_session(self, session: Session) -> None: ...

    def get_session(self, session_id: str) -> Session | None: ...

    def save_session(self, session: Session) -> None:
        """변경된 Session 을 저장한다. 상태 전이 뒤에는 항상 부른다."""
        ...

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
        self._summaries.clear()


store: Store = InMemoryStore()
