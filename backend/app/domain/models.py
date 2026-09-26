"""면접·세션 도메인 모델 — Notion `API 기본 명세서` 기준."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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


def utcnow() -> datetime:
    """도메인 시계. **앱 안에서 시각을 만드는 곳은 여기 하나다.**

    저장소 구현도 이걸 쓴다. DB 의 `now()` 를 섞으면 두 시계의 차이만큼 한도가
    늘거나 줄고, 인메모리와 DB 의 판정 기준도 달라진다.
    """
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


@dataclass
class Interview:
    interviewer_id: str
    candidate_name: str | None = None
    id: str = field(default_factory=lambda: _new_id("int"))
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class Session:
    interview_id: str
    id: str = field(default_factory=lambda: _new_id("ses"))
    status: SessionStatus = SessionStatus.WAITING
    created_at: datetime = field(default_factory=utcnow)
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
        self.started_at = utcnow()
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
        self.ended_at = utcnow()
        return True


#: 컨텍스트의 기본 주인.
#:
#: FE 는 이 설정을 「조직당 하나」로 그린다 — 「조직 하나가 공유하는 면접 기준」
#: (`ContextSettingsPage.tsx`). 그런데 조직도 로그인도 아직 없어서 조직을 가릴 방법이
#: 없다. FE 도 같은 이유로 `contextId` 를 상수로 두고 있다 (「조직 컨텍스트를
#: 알려주는 API 가 없어 contextId 를 상수로 둔다」).
#:
#: 그래서 지금은 주인이 하나뿐이고, 컨텍스트도 하나다. 로그인이 들어오면 토큰에서
#: 주인을 정하게 되고 그때 이 상수가 사라진다 — 컬럼은 `owner_id` 로 두었으니
#: 스키마는 그대로 쓴다.
DEFAULT_CONTEXT_OWNER = "__default__"


@dataclass
class Context:
    """기업 컨텍스트 — 회사·직무·인재상과 올려 둔 문서.

    **면접이 아니라 조직에 딸린다.** 회사 정보와 JD 는 면접마다 바뀌지 않으므로
    설정에 한 번 넣고 계속 쓴다 (#79). 주인당 하나다.
    """

    owner_id: str = DEFAULT_CONTEXT_OWNER
    id: str = field(default_factory=lambda: _new_id("ctx"))
    company: str = ""
    team: str = ""
    role: str = ""
    #: AI 면접관이 참고할 추가 인재상·평가 포인트 (#81).
    talent_profile: str = ""
    created_at: datetime = field(default_factory=utcnow)


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
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class Resume:
    """지원자 이력서 — 면접 한 건에 한 장.

    `ContextDoc` 과 모양이 거의 같지만 주인이 다르다. 기업 컨텍스트는 조직에 딸려
    여러 면접이 함께 쓰고, 이력서는 면접 한 건의 것이다. 한 테이블에 섞으면 「이
    문서가 누구 것인가」가 컬럼 값으로만 갈려 조회마다 조건이 붙는다.

    다시 올리면 덮어쓴다 — FE 가 목록도 삭제도 두지 않았다(#81).
    """

    interview_id: str
    name: str
    kind: DocKind
    size_bytes: int
    id: str = field(default_factory=lambda: _new_id("doc"))
    status: DocStatus = DocStatus.READY
    created_at: datetime = field(default_factory=utcnow)


class SummaryStatus(StrEnum):
    """면접 요약의 상태. FE 의 `SummaryStatus` 와 같은 값이다.

    PROCESSING --Agent 가 결과를 써 넣음--> READY
               --기다리다 한도를 넘김----> FAILED

    FE 는 PROCESSING 동안만 다시 조회한다. 그래서 **종료 상태가 반드시 와야
    한다** — 아무도 결과를 안 써 주면 화면이 영원히 돈다. 그 마감을 서버가
    맡는 것이 `SUMMARY_TIMEOUT_SECONDS` 다.
    """

    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


@dataclass
class SessionSummary:
    """세션 하나의 요약. 면접이 끝나는 순간 PROCESSING 으로 태어난다.

    본문을 만드는 것은 Agent 이고(#70), 여기는 그 결과를 받아 두는 자리다.
    Agent 가 아직 안 붙어 있어도 상태 기계는 그대로 돈다 — 한도까지 기다렸다
    FAILED 로 간다. 붙고 나면 같은 코드가 READY 를 낸다.
    """

    session_id: str
    status: SummaryStatus = SummaryStatus.PROCESSING
    overview: str = ""
    key_points: list[str] = field(default_factory=list)
    requested_at: datetime = field(default_factory=utcnow)
    completed_at: datetime | None = None

    def overdue(self, limit: timedelta, now: datetime | None = None) -> bool:
        """기다린 시간이 한도를 넘었나. 이미 끝난 요약은 언제 봐도 False 다.

        한도를 인자로 받는다 — 도메인은 설정을 읽지 않는다. 부르는 쪽이
        `settings.summary_timeout` 을 넘긴다.
        """
        if self.status is not SummaryStatus.PROCESSING:
            return False
        return (now or utcnow()) - self.requested_at > limit

    def complete(self, overview: str, key_points: list[str]) -> None:
        """Agent 가 만든 요약을 받는다."""
        self.status = SummaryStatus.READY
        self.overview = overview
        self.key_points = list(key_points)
        self.completed_at = utcnow()

    def give_up(self) -> None:
        """요약을 못 만들었다고 확정한다. 본문은 비운다."""
        self.status = SummaryStatus.FAILED
        self.overview = ""
        self.key_points = []
        self.completed_at = utcnow()
