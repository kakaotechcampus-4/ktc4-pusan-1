"""면접·세션 도메인 모델 — Notion `API 기본 명세서` 기준."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class SessionStatus(StrEnum):
    """Session 상태. 명세 예시가 WAITING / INTERVIEWING / ENDED 다.

    WAITING --start--> INTERVIEWING --end--> ENDED

    WAITING 에서 바로 end 할 수 있다(면접 시작 전 취소).
    """

    WAITING = "WAITING"
    INTERVIEWING = "INTERVIEWING"
    ENDED = "ENDED"


class Role(StrEnum):
    """입장 권한. 명세의 Request Body 예시가 `"role": "CANDIDATE"` 다."""

    INTERVIEWER = "INTERVIEWER"
    CANDIDATE = "CANDIDATE"


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


@dataclass
class Interview:
    interviewer_id: str
    id: str = field(default_factory=lambda: _new_id("int"))
    created_at: datetime = field(default_factory=_now)


@dataclass
class Session:
    interview_id: str
    id: str = field(default_factory=lambda: _new_id("ses"))
    status: SessionStatus = SessionStatus.WAITING
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @property
    def room_name(self) -> str:
        """LiveKit Room 이름. 명세 예시가 `interview_ses_123` 이다."""
        return f"interview_{self.id}"

    def start(self) -> bool:
        """면접 진행 상태로 전이. WAITING 이 아니면 False.

        명세의 409 `현재 상태에서 시작할 수 없음` 에 해당한다.
        """
        if self.status is not SessionStatus.WAITING:
            return False
        self.status = SessionStatus.INTERVIEWING
        self.started_at = _now()
        return True

    def end(self) -> bool:
        """종료 상태로 전이. 이미 ENDED 면 False.

        명세의 409 `현재 상태에서 종료할 수 없음` 에 해당한다.
        """
        if self.status is SessionStatus.ENDED:
            return False
        self.status = SessionStatus.ENDED
        self.ended_at = _now()
        return True
