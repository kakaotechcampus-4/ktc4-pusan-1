"""요청·응답 모델 — Notion `API 기본 명세서` 의 Request/Response 표를 그대로 옮긴 것.

FE 는 camelCase 를 쓴다. 파이썬 쪽은 snake_case 로 두고 alias 로 변환한다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import DocKind, DocStatus, Role, SessionStatus, SummaryStatus


class Schema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ── 면접 ────────────────────────────────────────────────


class CreateInterviewRequest(Schema):
    interviewer_id: str = Field(
        alias="interviewerId", min_length=1, max_length=64, examples=["user_123"]
    )
    candidate_name: str | None = Field(
        default=None,
        alias="candidateName",
        max_length=20,
        examples=["김지원"],
        description="면접관 화면에 표시할 지원자 이름. 비우면 기본 라벨을 쓴다.",
    )


class InterviewResponse(Schema):
    interview_id: str = Field(serialization_alias="interviewId")
    interviewer_id: str = Field(serialization_alias="interviewerId")
    candidate_name: str | None = Field(serialization_alias="candidateName")
    created_at: datetime = Field(serialization_alias="createdAt")


# ── 세션 ────────────────────────────────────────────────


class CreateSessionResponse(Schema):
    session_id: str = Field(serialization_alias="sessionId")
    interview_id: str = Field(serialization_alias="interviewId")
    candidate_name: str | None = Field(serialization_alias="candidateName")
    status: SessionStatus
    invite_url: str = Field(
        serialization_alias="inviteUrl", description="지원자에게 전달할 면접 링크"
    )
    created_at: datetime = Field(serialization_alias="createdAt")


class SessionStateResponse(Schema):
    """GET /sessions/{sessionId} — 새로고침·재접속 시 상태 복구용."""

    session_id: str = Field(serialization_alias="sessionId")
    interview_id: str = Field(serialization_alias="interviewId")
    candidate_name: str | None = Field(serialization_alias="candidateName")
    status: SessionStatus
    started_at: datetime | None = Field(
        serialization_alias="startedAt",
        description="「면접 시작」 버튼을 누른 시각. 안 누르고 끝나면 비어 있다.",
    )
    ended_at: datetime | None = Field(serialization_alias="endedAt")
    transcript_origin_at: datetime | None = Field(
        serialization_alias="transcriptOriginAt",
        description=(
            "전사 타임라인의 원점(t=0). 첫 참가자가 입장한 시각이고 "
            "LiveKit Webhook 이 채운다. AI 의 startMs 와 FE 의 atSec 은 "
            "단위만 다르고 원점은 이 값을 쓴다. startedAt 과는 다른 값이다."
        ),
    )


class StartSessionResponse(Schema):
    session_id: str = Field(serialization_alias="sessionId")
    status: SessionStatus
    started_at: datetime = Field(serialization_alias="startedAt")


class EndSessionResponse(Schema):
    session_id: str = Field(serialization_alias="sessionId")
    status: SessionStatus
    ended_at: datetime = Field(serialization_alias="endedAt")


# ── 진입 ────────────────────────────────────────────────


class JoinRequest(Schema):
    role: Role = Field(
        default=Role.CANDIDATE,
        description=(
            "현재 로그인·인증 제외 기준이라 요청값으로 받는다. "
            "인증 도입 후에는 서버가 참가자 역할을 판단한다."
        ),
    )


class JoinResponse(Schema):
    session_id: str = Field(serialization_alias="sessionId")
    candidate_name: str | None = Field(serialization_alias="candidateName")
    livekit_url: str = Field(
        serialization_alias="livekitUrl", description="LiveKit 서버 접속 URL"
    )
    token: str = Field(description="LiveKit Room 입장용 Access Token")
    room_name: str = Field(
        serialization_alias="roomName", description="매핑된 LiveKit Room 이름"
    )


# ── 면접 기록 ────────────────────────────────────────────
#
# ⚠️ 이 계약은 아직 세 파트가 합의하지 않았다. 아래는 FE 가
# `types/interview.ts` 에 적어 둔 모양을 그대로 옮긴 것이고, BE 는 지금
# PROCESSING 만 돌려준다. 합의 전까지 READY 응답은 나가지 않는다.
#
# 남은 쟁점 (회의 안건)
#   1. 키를 interviewId 로 둘지 sessionId 로 둘지
#      — FE 는 interviewId, AI 의 TimelineResult 는 session_id 다.
#        면접 하나에 세션이 여럿이라 그냥 같은 값이 아니다.
#   2. 단위 — FE 는 초(atSec), AI 는 밀리초(atMs)
#   3. recording.hlsUrl — 녹화(Egress) 가 아직 없다. FE 도 "가정했다"고 적어 뒀다.


class ReviewMoment(Schema):
    """질문 하나가 시작된 시점과 그 문답."""

    id: str
    at_sec: int = Field(
        serialization_alias="atSec",
        description=(
            "전사 원점 기준 경과 초. 원점은 첫 참가자 접속 시각으로 합의했고, "
            "Session 에 별도 필드로 신설한다 (별도 이슈)."
        ),
    )
    label: str = Field(description="타임라인 아래 짧은 라벨")
    question: str = Field(description="면접관 발화 원문")
    answer: str = Field(description="답변 요약 한두 줄")


class ReviewRecording(Schema):
    hls_url: str = Field(serialization_alias="hlsUrl")


class ReviewCandidate(Schema):
    name: str
    role: str


class ReviewAiReview(Schema):
    paragraphs: list[str] = Field(
        description="전사·지원서·JD 를 근거로 쓴 서술. 합격 여부는 담지 않는다."
    )


class ReviewReadyResponse(Schema):
    """준비가 끝난 면접 기록.

    ⚠️ 아직 어떤 경로로도 나가지 않는다. 계약을 명세에 박아 두기 위한 모델이다.
    """

    status: Literal["READY"] = "READY"
    interview_id: str = Field(serialization_alias="interviewId")
    candidate: ReviewCandidate
    duration_sec: int = Field(serialization_alias="durationSec")
    recording: ReviewRecording
    moments: list[ReviewMoment]
    ai_review: ReviewAiReview = Field(serialization_alias="aiReview")


class ReviewProcessingResponse(Schema):
    """녹화 변환과 AI 평가가 아직 끝나지 않은 상태. 202 로 나간다."""

    status: Literal["PROCESSING"] = "PROCESSING"
    eta_sec: int | None = Field(
        default=None,
        serialization_alias="etaSec",
        description="남은 예상 시간. 추정할 근거가 없으면 비운다.",
    )


class SummaryContent(Schema):
    """요약 본문. `status` 가 READY 일 때만 찬다.

    모양은 FE 가 화면에 이미 그려 둔 것(`InterviewSummary['content']`)이고,
    AI 쪽 `SummaryResult` 의 `summary` · `keyPoints` 와 그대로 맞는다.
    """

    overview: str = Field(description="면접 전체를 한 문단으로.")
    key_points: list[str] = Field(
        serialization_alias="keyPoints", description="지원자 답변에서 뽑은 핵심."
    )


class SummaryResponse(Schema):
    """면접 요약 조회 응답. FE 의 `InterviewSummary` 와 같은 모양이다.

    `status` 는 지어낸 값이 아니라 저장된 상태다 — 면접이 끝나면 PROCESSING 으로
    태어나고, Agent 가 결과를 써 넣으면 READY, 한도를 넘기면 FAILED 다.

    `durationSec` 은 「면접 시작」과 「종료」 사이를 센다. 둘 중 하나가 비어 있으면
    0 이다 — 시작을 안 누르고 끝냈거나 아직 안 끝난 면접이다.
    """

    session_id: str = Field(serialization_alias="sessionId")
    status: SummaryStatus
    content: SummaryContent | None = Field(
        default=None, description="READY 일 때만 찬다."
    )
    duration_sec: int = Field(serialization_alias="durationSec")


# ── 기업 컨텍스트 ────────────────────────────────────────


class ContextDocResponse(Schema):
    """FE 의 `ContextDoc` 과 같은 모양.

    `progress` 는 내보내지 않는다 — 업로드 진행률은 클라이언트만 아는 값이다.
    """

    id: str
    name: str
    kind: DocKind
    size_bytes: int = Field(serialization_alias="sizeBytes")
    status: DocStatus


class ContextResponse(Schema):
    """FE 의 `CompanyContext` 에 `talentProfile` 을 더한 것.

    FE 가 「조회가 talentProfile 을 안 돌려줘서 새로 고치면 빈 칸에서 시작한다」고
    한계를 적어 뒀는데(#81), 저장만 되고 못 읽으면 쓸 수 없으므로 여기 싣는다.
    """

    id: str
    company: str
    team: str
    role: str
    talent_profile: str = Field(serialization_alias="talentProfile")
    docs: list[ContextDocResponse]


class UpdateContextRequest(Schema):
    """`PATCH /contexts/{contextId}` — 넣은 항목만 바꾼다.

    길이를 막아 둔다. FE 도 입력창에서 거르지만 그건 편의이지 경계가 아니다 —
    업로드에 같은 원칙을 쓰면서 여기만 열어 두면 앞뒤가 안 맞는다.
    """

    company: str | None = Field(default=None, max_length=100)
    team: str | None = Field(default=None, max_length=100)
    role: str | None = Field(default=None, max_length=100)
    talent_profile: str | None = Field(
        default=None, alias="talentProfile", max_length=4000
    )
