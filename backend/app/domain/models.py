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


class DocKind(StrEnum):
    """업로드할 수 있는 문서 형식. FE 의 `DocKind` 와 같다."""

    PDF = "pdf"
    DOCX = "docx"


class DocStatus(StrEnum):
    """서버가 아는 문서 상태.

    FE 의 `DocStatus` 에는 `uploading` 도 있지만 그건 클라이언트에만 있는 상태다 —
    서버는 업로드가 끝난 뒤에야 문서를 안다.

    `PARSING` 은 아직 쓰지 않는다. 본문 추출을 누가 하는지가 안 정해져서(#70) 지금은
    올라온 즉시 `READY` 다. 값은 미리 둔다 — 나중에 파싱이 붙을 때 FE 가 이미 이
    분기를 갖고 있다.
    """

    PARSING = "parsing"
    READY = "ready"
    FAILED = "failed"


class Role(StrEnum):
    """입장 권한. 명세의 Request Body 예시가 `"role": "CANDIDATE"` 다."""

    INTERVIEWER = "INTERVIEWER"
    CANDIDATE = "CANDIDATE"


#: LiveKit Room 이름 접두사. Webhook 이 방 이름만 주므로 여기서 세션을 되찾는다.
ROOM_PREFIX = "interview_"


def session_id_from_room(room_name: str) -> str | None:
    """Room 이름에서 세션 id 를 되돌린다. 우리 규칙이 아니면 None.

    LiveKit 은 우리가 만들지 않은 방에 대해서도 Webhook 을 보낼 수 있다
    (테스트 도구, 로드 테스트 등). 모르는 방은 조용히 무시한다.
    """
    if not room_name.startswith(ROOM_PREFIX):
        return None
    session_id = room_name[len(ROOM_PREFIX) :]
    return session_id or None


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


@dataclass
class Interview:
    interviewer_id: str
    candidate_name: str | None = None
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
    #: 전사 타임라인의 원점(t=0). 첫 참가자가 LiveKit Room 에 들어온 시각이다.
    #:
    #: `started_at` 과 일부러 분리했다 — 그쪽은 면접관이 「면접 시작」을 누른
    #: 비즈니스 시각이라 안 누르면 비어 있고, 마스터 클럭으로 쓸 수 없다.
    #: 이 값은 LiveKit Webhook(`participant_joined`)이 채운다.
    #:
    #: AI 의 `startMs` 와 FE 의 `atSec` 은 단위만 다르고 원점은 이 값 하나를 쓴다.
    #: 녹화(Egress) 도입 시 Egress start 와의 오프셋 보정 때문에 재검토한다.
    transcript_origin_at: datetime | None = None

    @property
    def room_name(self) -> str:
        """LiveKit Room 이름. 명세 예시가 `interview_ses_123` 이다."""
        return f"{ROOM_PREFIX}{self.id}"

    def start(self) -> bool:
        """면접 진행 상태로 전이. WAITING 이 아니면 False.

        명세의 409 `현재 상태에서 시작할 수 없음` 에 해당한다.
        """
        if self.status is not SessionStatus.WAITING:
            return False
        self.status = SessionStatus.INTERVIEWING
        self.started_at = _now()
        return True

    def mark_origin(self, at: datetime) -> bool:
        """전사 원점을 첫 참가자 입장 시각으로 고정한다.

        Webhook 은 재전송되고 두 참가자가 각각 이벤트를 만드므로 여러 번 불린다.
        처음 한 번만 쓰고 이후는 무시한다 — 원점이 뒤로 밀리면 이미 찍힌
        전사 타임스탬프가 전부 어긋난다.
        """
        if self.transcript_origin_at is not None:
            return False
        self.transcript_origin_at = at
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


@dataclass
class Context:
    """면접관의 기업 컨텍스트 — 회사·직무·인재상과 올려 둔 문서.

    **면접이 아니라 면접관에게 딸린다.** 회사 정보와 JD 는 면접마다 바뀌지 않으므로
    한 번 넣고 계속 쓰는 편이 맞다는 것이 #79 의 제안이고, 이 모델이 그걸 따른다.
    면접관 한 명에 하나다.
    """

    interviewer_id: str
    id: str = field(default_factory=lambda: _new_id("ctx"))
    company: str = ""
    team: str = ""
    role: str = ""
    #: AI 면접관이 참고할 추가 인재상·평가 포인트 (#81).
    talent_profile: str = ""
    created_at: datetime = field(default_factory=_now)


@dataclass
class ContextDoc:
    """컨텍스트에 올린 문서 한 건의 메타데이터.

    원본 바이트는 저장소가 따로 들고 있다 — 목록을 부를 때마다 파일 전체가 딸려
    오면 안 된다.
    """

    context_id: str
    name: str
    kind: DocKind
    size_bytes: int
    id: str = field(default_factory=lambda: _new_id("doc"))
    status: DocStatus = DocStatus.READY
    created_at: datetime = field(default_factory=_now)
