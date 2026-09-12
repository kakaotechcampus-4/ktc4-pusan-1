"""요청·응답 모델 — Notion `API 기본 명세서` 의 Request/Response 표를 그대로 옮긴 것.

FE 는 camelCase 를 쓴다. 파이썬 쪽은 snake_case 로 두고 alias 로 변환한다.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import Role, SessionStatus


class Schema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ── 면접 ────────────────────────────────────────────────


class CreateInterviewRequest(Schema):
    interviewer_id: str = Field(
        alias="interviewerId", min_length=1, max_length=64, examples=["user_123"]
    )


class InterviewResponse(Schema):
    interview_id: str = Field(serialization_alias="interviewId")
    interviewer_id: str = Field(serialization_alias="interviewerId")
    created_at: datetime = Field(serialization_alias="createdAt")


# ── 세션 ────────────────────────────────────────────────


class CreateSessionResponse(Schema):
    session_id: str = Field(serialization_alias="sessionId")
    interview_id: str = Field(serialization_alias="interviewId")
    status: SessionStatus
    invite_url: str = Field(
        serialization_alias="inviteUrl", description="지원자에게 전달할 면접 링크"
    )
    created_at: datetime = Field(serialization_alias="createdAt")


class SessionStateResponse(Schema):
    """GET /sessions/{sessionId} — 새로고침·재접속 시 상태 복구용."""

    session_id: str = Field(serialization_alias="sessionId")
    interview_id: str = Field(serialization_alias="interviewId")
    status: SessionStatus
    started_at: datetime | None = Field(serialization_alias="startedAt")
    ended_at: datetime | None = Field(serialization_alias="endedAt")


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
    livekit_url: str = Field(
        serialization_alias="livekitUrl", description="LiveKit 서버 접속 URL"
    )
    token: str = Field(description="LiveKit Room 입장용 Access Token")
    room_name: str = Field(
        serialization_alias="roomName", description="매핑된 LiveKit Room 이름"
    )
