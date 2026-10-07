"""요청·응답 모델 — Notion `API 기본 명세서` 의 Request/Response 표를 그대로 옮긴 것.

FE 는 camelCase 를 쓴다. 파이썬 쪽은 snake_case 로 두고 alias 로 변환한다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import (
    CoverageState,
    DocCategory,
    DocKind,
    DocStatus,
    FindingState,
    FindingType,
    ReviewStatus,
    Role,
    SessionStatus,
    SummaryStatus,
)


class Schema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ── 면접 ────────────────────────────────────────────────


class CreateInterviewRequest(Schema):
    # 면접의 주인은 토큰의 사용자다 (#130). 예전 FE 가 `interviewerId` 를 보내도
    # 스키마가 모르는 필드라 조용히 무시된다.
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


class InterviewerSummary(Schema):
    nickname: str


class ReviewCounts(Schema):
    """목록 한 줄의 집계. 상세와 같은 계산(`app/services/review.py`)에서 나온다."""

    coverage_confirmed: int = Field(alias="coverageConfirmed")
    coverage_total: int = Field(alias="coverageTotal")
    findings: int
    needs_review: int = Field(
        alias="needsReview", description="아직 채택도 반려도 안 한 검토 항목"
    )
    adopted: int


class InterviewListItem(Schema):
    """`GET /interviews` 의 한 줄. 지원자 목록 화면(`/candidates`)이 그린다 (#137 1-1).

    기준은 그 면접의 마지막으로 끝난 세션이다. 끝난 세션이 없으면 그 세션에서 오는
    값(`interviewedAt` · `durationSec` · `summaryStatus`)은 null 이다.
    """

    interview_id: str = Field(serialization_alias="interviewId")
    candidate_name: str | None = Field(serialization_alias="candidateName")
    role: str = Field(description="컨텍스트의 직무. 아직 안 정했으면 빈 문자열.")
    interviewer: InterviewerSummary
    interviewed_at: datetime | None = Field(
        serialization_alias="interviewedAt",
        description="「면접 시작」 시각. 비어 있으면 첫 입장 시각.",
    )
    duration_sec: int | None = Field(serialization_alias="durationSec")
    review_status: ReviewStatus = Field(serialization_alias="reviewStatus")
    summary_status: SummaryStatus | None = Field(
        serialization_alias="summaryStatus",
        description="한도를 넘긴 PROCESSING 은 FAILED 로 보인다(저장값은 그대로).",
    )
    counts: ReviewCounts | None = Field(
        description="검토 항목 집계. 요약이 READY 가 아니면 null 이다 (#137 1-1)."
    )


class InterviewListResponse(Schema):
    items: list[InterviewListItem]


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
            "입장할 역할. `CANDIDATE` 는 누구나 된다. `INTERVIEWER` 는 그 면접을 만든 "
            "사용자의 토큰이 있어야 한다 — 없으면 401, 다른 사용자면 403 "
            "`ROLE_NOT_ALLOWED`. 서버는 역할을 바꾸지 않고 검증만 한다."
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


# ── 면접 기록 (검토 상세) ────────────────────────────────
#
# 모양은 #137 1-2 다. 녹화는 싣지 않고 기준 세션의 `sessionId` 를 싣는다 — FE 가
# 그 id 로 녹화 API 를 부른다 (#163). 계산 규칙은 `app/services/review.py`.


class RecordingResponse(Schema):
    """녹화 재생 (#112). 합친 파일 하나의 서명 URL 이다.

    `offsetMs` 는 녹화의 0초가 전사 원점(t=0)보다 얼마나 뒤인가다. 전사 시각
    t(ms) 의 장면은 녹화의 `t − offsetMs` 에 있다.
    """

    url: str
    expires_at: datetime = Field(serialization_alias="expiresAt")
    offset_ms: int = Field(serialization_alias="offsetMs")
    duration_sec: int = Field(serialization_alias="durationSec")


class SummaryContent(Schema):
    """요약 본문. `status` 가 READY 일 때만 찬다.

    모양은 FE 가 화면에 이미 그려 둔 것(`InterviewSummary['content']`)이고,
    AI 쪽 `SummaryResult` 의 `summary` · `keyPoints` 와 그대로 맞는다.
    """

    overview: str = Field(description="면접 전체를 한 문단으로.")
    key_points: list[str] = Field(
        serialization_alias="keyPoints", description="지원자 답변에서 뽑은 핵심."
    )


class ReviewCandidate(Schema):
    name: str | None = Field(description="비어 있으면 FE 가 기본 라벨로 대체한다.")
    role: str = Field(description="컨텍스트의 직무. 아직 안 정했으면 빈 문자열.")


class ReviewCoverage(Schema):
    name: str = Field(description="역량 이름")
    state: CoverageState


class ReviewMoment(Schema):
    """질문 하나가 시작된 시점과 그 문답."""

    id: str
    # `alias` 다 — 계산 결과(camelCase dict)를 그대로 받아 그대로 낸다.
    at_sec: float = Field(alias="atSec", description="전사 원점 기준 경과 초")
    label: str = Field(description="타임라인 아래 짧은 라벨")
    question: str = Field(description="면접관 발화 원문")
    answer: str = Field(description="답변 요약 한두 줄")
    competencies: list[str] = Field(
        description="근거 시각이 이 문답 구간에 드는 검토 항목의 역량"
    )
    bookmarked: bool


class ReviewFinding(Schema):
    """검토 항목 하나 — AI 가 근거와 함께 낸 관찰. 판정이 아니다."""

    id: str
    type: FindingType
    competency: str | None
    source: str | None = Field(description="「지원서 · 단락」 또는 「면접 답변」")
    quote: str | None = Field(description="지원서의 문장")
    transcript: str | None = Field(description="근거가 된 면접 발화")
    rationale: str
    at_sec: float | None = Field(alias="atSec")
    state: FindingState


class ReviewResponse(Schema):
    """준비가 끝난 면접 기록 (#137 1-2).

    요약이 FAILED 여도 이 모양이다 — `summary` 는 null, moments · findings 는 비고
    coverage 는 역량 전부 MISSING 이다. 메모 · 검토 확정은 AI 결과와 상관없이 할 수
    있어야 한다 (#163).
    """

    # 기본값을 두지 않는다 — 두면 OpenAPI 에서 판별 필드가 선택으로 보인다.
    status: Literal["READY"]
    summary_status: Literal[SummaryStatus.READY, SummaryStatus.FAILED] = Field(
        serialization_alias="summaryStatus"
    )
    interview_id: str = Field(serialization_alias="interviewId")
    session_id: str = Field(
        serialization_alias="sessionId",
        description="기준 세션. 녹화는 이 id 로 `GET /sessions/{sessionId}/recording`",
    )
    candidate: ReviewCandidate
    interviewer: InterviewerSummary
    interviewed_at: datetime | None = Field(serialization_alias="interviewedAt")
    duration_sec: int | None = Field(serialization_alias="durationSec")
    review_status: ReviewStatus = Field(serialization_alias="reviewStatus")
    reviewed_at: datetime | None = Field(serialization_alias="reviewedAt")
    memo: str
    summary: SummaryContent | None
    coverage: list[ReviewCoverage]
    moments: list[ReviewMoment]
    findings: list[ReviewFinding]


class ReviewUpdateRequest(Schema):
    """`PATCH /interviews/{interviewId}` — 검토 상태 · 메모 (#137 1-3). 둘 다 선택이다.

    null 은 보내지 않은 것과 같다. 메모를 비우려면 빈 문자열을 보낸다. 길이와 NUL 은
    경계에서 막는다 — PostgreSQL TEXT 는 NUL 을 못 넣어 500 이 된다.
    """

    review_status: ReviewStatus | None = Field(default=None, alias="reviewStatus")
    memo: str | None = Field(default=None, max_length=4000, pattern=r"^[^\x00]*$")


class ReviewUpdateResponse(Schema):
    review_status: ReviewStatus = Field(serialization_alias="reviewStatus")
    reviewed_at: datetime | None = Field(
        serialization_alias="reviewedAt",
        description="CONFIRMED 가 된 시각. 다른 상태로 돌아가면 null.",
    )
    memo: str


class MarkUpdateRequest(Schema):
    """`PUT .../review/marks/{itemId}` — 채택 · 북마크 (#137 1-4). 보낸 것만 바뀐다.

    `state` 는 검토 항목(finding)의 채택 여부, `bookmarked` 는 문답(moment)의
    북마크다. 둘 다 없으면 바꿀 것이 없어 422 다.
    """

    state: FindingState | None = None
    bookmarked: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "MarkUpdateRequest":
        if self.state is None and self.bookmarked is None:
            raise ValueError("state 나 bookmarked 중 하나는 있어야 한다")
        return self


class MarkResponse(Schema):
    """그 항목의 지금 표시."""

    item_id: str = Field(serialization_alias="itemId")
    state: FindingState
    bookmarked: bool


class ReviewProcessingResponse(Schema):
    """녹화 변환과 AI 평가가 아직 끝나지 않은 상태. 202 로 나간다."""

    status: Literal["PROCESSING"] = "PROCESSING"
    eta_sec: int | None = Field(
        default=None,
        serialization_alias="etaSec",
        description="남은 예상 시간. 추정할 근거가 없으면 비운다.",
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
    status: DocStatus = Field(
        description=(
            "올라온 직후는 parsing 이다. 본문을 뽑으면 ready, 못 뽑으면 failed. "
            "parsing 인 동안 다시 조회한다."
        )
    )
    category: DocCategory | None = Field(
        default=None,
        description="기업 컨텍스트 문서의 칸(jd · internal). 이력서는 null.",
    )


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


# ── 인증 ────────────────────────────────────────────────


class KakaoLoginRequest(Schema):
    code: str = Field(
        min_length=1,
        max_length=512,
        description="카카오가 FE 콜백으로 넘겨 준 `code`. 한 번만 쓸 수 있다.",
    )


class UserResponse(Schema):
    id: str
    nickname: str = Field(description="카카오 닉네임. 콘솔에서 필수 동의 항목이다.")
    profile_image_url: str | None = Field(serialization_alias="profileImageUrl")


class LoginResponse(Schema):
    access_token: str = Field(
        serialization_alias="accessToken",
        description="이후 요청의 `Authorization: Bearer` 에 싣는다.",
    )
    user: UserResponse
