"""`/internal/v1` 의 요청 모델 — Agent 가 보내는 것.

`app/schemas.py` 와 나눠 둔다. 저쪽은 브라우저가 보는 공개 명세고 이건 Agent 와
우리 사이의 내부 계약이라, 한 파일에 섞이면 어느 쪽을 바꿔도 되는지가 흐려진다.

필드 이름은 Agent 가 보내는 그대로다 (`irya_ai.schemas.wire`). 검증을 세게 걸어
둔 곳이 둘 있다.

* `evidenceUtteranceIds` 는 **비어 있을 수 없다.** 근거를 못 대는 꼬리질문은
  만들지 않는 것이 AI 쪽 파이프라인의 원칙이고, 경계에서도 그걸 말한다.
* `endedAtMs` 는 `startedAtMs` 보다 앞설 수 없다. Agent 쪽 `Utterance` 가 같은
  검증을 갖고 있어 여기서도 같이 막아 둔다.

그리고 **저장할 수 없는 값은 여기서 거른다.** PostgreSQL 은 TEXT 에 NUL 문자를
못 넣고 BIGINT 는 2^63 을 못 넘는다. 이런 프레임이 검증을 통과하면 저장에서
실패하고, 우리는 연결을 끊고(`transcripts.py`), Agent 는 다시 붙어 **그 프레임부터**
다시 보낸다 — 끝나지 않는다. 여기서 막으면 그 발화 하나만 NACK 으로 버려진다.
"""

from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
from pydantic.alias_generators import to_camel

from app.domain.models import JobKind, Role

FRAME_UPSERT: Final = "transcript.upsert"
FRAME_ACK: Final = "transcript.ack"
FRAME_NACK: Final = "transcript.nack"

#: BIGINT 의 상한. 발화 시각과 순번(`seq`)은 이 컬럼에 들어간다 (`schema.sql`).
BIGINT_MAX: Final = 2**63 - 1


def _no_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("NUL 문자는 저장할 수 없다")
    return value


#: DB 의 TEXT 에 들어갈 문자열. 비어 있을 수 없다.
PgText = Annotated[str, Field(min_length=1), AfterValidator(_no_nul)]

#: 비어 있어도 되는 쪽. JSONB 도 NUL(`\u0000`)을 못 넣는다.
PgAnyText = Annotated[str, AfterValidator(_no_nul)]


def _dedupe(ids: list[str]) -> list[str]:
    """처음 나온 순서를 지키며 중복을 지운다. 근거는 위치로 저장된다."""
    return list(dict.fromkeys(ids))


class InternalSchema(BaseModel):
    """모르는 필드는 **무시한다.**

    처음에는 `extra="forbid"` 로 두었다. 계약이 어긋나면 조용히 버려지는 대신
    드러나야 한다고 봤기 때문인데, 실패 방식이 너무 나쁘다 — Agent 가
    `TranscriptPayload` 에 필드를 하나 더하면 **모든 프레임이 NACK** 이 되고,
    받는 쪽이 아직 NACK 을 처리하지 않아서 면접 내내 재연결 루프가 된다.

    필드가 늘어난 프레임은 우리가 아는 부분만 읽어도 맞는 값이다. 계약이 갈라지는
    것은 명세 잠금 테스트와 계약 테스트가 잡는다 — 운영 중에 잡을 일이 아니다.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class TranscriptUpsert(InternalSchema):
    """`WS /internal/v1/sessions/{sessionId}/transcripts` 의 프레임 하나.

    세션은 경로에 있고 본문에 없다. 본문에도 넣으면 URL 과 다른 값이 실려올 수
    있고, 그때 어느 쪽을 믿을지가 또 규칙이 된다.
    """

    type: Literal["transcript.upsert"]
    utterance_id: PgText = Field(alias="utteranceId")
    participant_id: PgText = Field(alias="participantId")
    speaker: Role
    text: PgText
    started_at_ms: int = Field(alias="startedAtMs", ge=0, le=BIGINT_MAX)
    ended_at_ms: int = Field(alias="endedAtMs", ge=0, le=BIGINT_MAX)
    # PR #158 부터 온다. 그 전 Agent 의 프레임도 받도록 비워 둘 수 있다.
    track_id: PgText | None = Field(default=None, alias="trackId")
    seq: int | None = Field(default=None, ge=0, le=BIGINT_MAX)

    @model_validator(mode="after")
    def _check_range(self) -> "TranscriptUpsert":
        if self.ended_at_ms < self.started_at_ms:
            raise ValueError("endedAtMs must be >= startedAtMs")
        return self


class TranscriptAck(InternalSchema):
    """받았다는 답. Agent 는 이걸 받아야 버퍼에서 발화를 지운다."""

    type: Literal["transcript.ack"] = FRAME_ACK
    utterance_id: str = Field(serialization_alias="utteranceId")


class TranscriptNack(InternalSchema):
    """받을 수 없다는 답. **다시 보내지 말라**는 뜻이다.

    Agent 는 이걸 받으면 그 발화를 버리고 다음으로 넘어간다 (#97).
    """

    type: Literal["transcript.nack"] = FRAME_NACK
    utterance_id: str = Field(serialization_alias="utteranceId")
    reason: str = Field(description="지금은 SCHEMA 하나뿐이다.")


class SuggestionCreate(InternalSchema):
    """꼬리질문 하나: suggestionId · content · evidenceUtteranceIds.

    `POST /internal/v1/sessions/{sessionId}/suggestions` 는 꼬리질문만 받아
    type 구분자를 두지 않는다. 세션은 URL 로 식별한다.
    """

    suggestion_id: PgText = Field(alias="suggestionId")
    content: PgText
    evidence_utterance_ids: Annotated[list[PgText], AfterValidator(_dedupe)] = Field(
        alias="evidenceUtteranceIds", min_length=1
    )


class ReviewUpsert(InternalSchema):
    """`PUT /internal/v1/sessions/{sessionId}/review` 의 본문 — 최종 리뷰 결과.

    `status` 는 AI 쪽 `AnalysisResult.status` 를 그대로 받는다. 네 값을 화면의 두
    값(READY · FAILED)으로 줄이는 매핑은 라우터 한 곳에만 둔다 — **Agent 는 무슨
    일이 있었는지를 말하고, 사용자에게 무엇을 보일지는 우리가 정한다.** Agent 쪽에
    번역을 시키면 같은 판단이 두 군데로 갈라진다.

    본문은 `AnalysisResult.summary_result` 의 `summary` · `keyPoints` 다. 근거
    인용(`points[]`)은 `Finding` 쪽이라 여기 범위가 아니다. 면접이 끝난 뒤의
    분석 결과라 최종 리뷰(#70)에서 다룬다 — 면접 중에 들어오는 전사·꼬리질문
    (#85)과 다르다.
    """

    status: Literal["completed", "partial", "empty", "failed"]
    summary: str = ""
    key_points: list[str] = Field(default_factory=list, alias="keyPoints")

    @model_validator(mode="after")
    def _done_means_there_is_something_to_show(self) -> "ReviewUpsert":
        # 본문 없이 READY 로 넘어가면 FE 는 `content` 가 객체라는 이유로 요약
        # 카드를 그리고, 그 안이 비어 있다. 실패로 두는 편이 맞다.
        if self.status in ("completed", "partial") and not self.summary.strip():
            raise ValueError("completed/partial 이면 summary 가 비어 있을 수 없다")
        return self


# ── AI 분석 작업 (#162) ─────────────────────────────────────


class AiShape(InternalSchema):
    """AI 의 `CamelModel` 과 같은 모양 — 파이썬은 snake_case, JSON 은 camelCase.

    필드가 많아 하나하나 alias 를 달지 않고 규칙으로 맞춘다.
    """

    model_config = ConfigDict(alias_generator=to_camel)


class PendingJob(AiShape):
    """`GET /internal/v1/jobs/pending` — 할 일 하나 (#137 2-2).

    `requestedAt` 은 결과를 보낼 때 그대로 돌려줘야 한다. 그 사이 다시 요청된
    작업이면 결과를 409 로 거절한다.
    """

    kind: JobKind
    session_id: str
    interview_id: str
    requested_at: datetime


class Competency(AiShape):
    """AI `Competency` (`schemas/context.py`). 이대로 JSON 으로 저장해 돌려준다."""

    competency_id: PgText
    jd_id: PgText
    name: PgText
    required: bool = True
    description: PgAnyText | None = None


class ResumeClaim(AiShape):
    """AI `ResumeClaim`. `quote` 는 이력서 본문에 그대로 있는 문장이다."""

    claim_id: PgText
    resume_id: PgText
    quote: PgText
    section: PgAnyText | None = None


class PrepUpsert(AiShape):
    """`PUT /internal/v1/interviews/{interviewId}/prep` — AI `PrepResult` (PR #156).

    `sessionId` · `rejections` · `warnings` · `usage` 같은 나머지는 받고 버린다.

    `requestedAt` 은 받은 작업의 것을 그대로 돌려받는다. 시간대가 없으면 저장된 값과
    비교할 수 없어 422 다.
    """

    status: Literal["completed", "partial", "empty", "failed"]
    requested_at: AwareDatetime
    model: PgAnyText = ""
    competencies: list[Competency] = Field(default_factory=list)
    resume_claims: list[ResumeClaim] = Field(default_factory=list)
