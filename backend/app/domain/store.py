"""저장소 인터페이스와 인메모리 구현.

라우터는 이 Protocol 에만 의존한다. 실제 구현은 `app/infra/postgres.py` 이고,
테스트와 로컬 기동은 아래 인메모리 구현을 그대로 쓴다.

⚠️ `save_session` 을 반드시 불러야 한다. 인메모리 구현은 객체를 참조로 돌려주므로
상태를 바꾸면 저장소에도 반영되지만, DB 구현은 그렇지 않다. 저장을 빠뜨리면
응답은 정상인데 재조회하면 이전 상태가 나오는 식으로 조용히 깨진다.
"""

from typing import Protocol

from app.domain.models import Interview, Session, SessionStatus


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


class InMemoryStore:
    def __init__(self) -> None:
        self._interviews: dict[str, Interview] = {}
        self._sessions: dict[str, Session] = {}
        # 마지막으로 저장된 상태. 세션 객체를 참조로 돌려주는 탓에 save_session
        # 시점에는 호출자가 이미 상태를 바꿔 놓아서, 객체만 봐서는 "저장소가
        # 알던 상태"를 알 수 없다. DB 구현과 같은 계약을 주려면 따로 들고 있어야 한다.
        self._saved_status: dict[str, SessionStatus] = {}

    def add_interview(self, interview: Interview) -> None:
        self._interviews[interview.id] = interview

    def get_interview(self, interview_id: str) -> Interview | None:
        return self._interviews.get(interview_id)

    def add_session(self, session: Session) -> None:
        self._sessions[session.id] = session
        self._saved_status[session.id] = session.status

    def get_session(self, session_id: str) -> Session | None:
        # 값을 그대로 돌려준다. 라우터가 상태를 바꾸면 저장소에도 반영된다.
        return self._sessions.get(session_id)

    def save_session(
        self, session: Session, *, expected_status: SessionStatus | None = None
    ) -> bool:
        # 객체 저장은 참조가 같아 사실상 no-op 이지만, 라우터가 DB 구현에서도
        # 똑같이 동작하도록 호출 규약을 맞춰 둔다.
        #
        # 없는 세션은 쓰지 않는다. DB 구현의 UPDATE 가 0행을 바꾸는 것과 같다 —
        # `save_session` 은 갱신이지 추가가 아니다 (추가는 `add_session`).
        if session.id not in self._sessions:
            return False
        if expected_status is not None:
            if self._saved_status.get(session.id) is not expected_status:
                return False
        self._sessions[session.id] = session
        self._saved_status[session.id] = session.status
        return True

    def clear(self) -> None:
        """테스트용."""
        self._interviews.clear()
        self._sessions.clear()
        self._saved_status.clear()


store: Store = InMemoryStore()
