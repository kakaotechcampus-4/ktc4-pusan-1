"""저장소 인터페이스와 인메모리 구현.

DB 는 아직 정해지지 않았다. 라우터가 Protocol 에만 의존하게 두어
구현체를 갈아끼우는 것으로 붙일 수 있게 한다.

⚠️ 인메모리라 서버를 재시작하면 세션 상태가 사라진다. LiveKit 은 별도 프로세스라
진행 중인 통화 자체는 끊기지 않지만, `GET /sessions/{id}` 로 상태를 복구하려면
DB 가 붙어야 한다.
"""

from typing import Protocol

from app.domain.models import Interview, Session


class Store(Protocol):
    def add_interview(self, interview: Interview) -> None: ...

    def get_interview(self, interview_id: str) -> Interview | None: ...

    def add_session(self, session: Session) -> None: ...

    def get_session(self, session_id: str) -> Session | None: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._interviews: dict[str, Interview] = {}
        self._sessions: dict[str, Session] = {}

    def add_interview(self, interview: Interview) -> None:
        self._interviews[interview.id] = interview

    def get_interview(self, interview_id: str) -> Interview | None:
        return self._interviews.get(interview_id)

    def add_session(self, session: Session) -> None:
        self._sessions[session.id] = session

    def get_session(self, session_id: str) -> Session | None:
        # 값을 그대로 돌려준다. 라우터가 상태를 바꾸면 저장소에도 반영된다.
        return self._sessions.get(session_id)

    def clear(self) -> None:
        """테스트용."""
        self._interviews.clear()
        self._sessions.clear()


store: Store = InMemoryStore()
