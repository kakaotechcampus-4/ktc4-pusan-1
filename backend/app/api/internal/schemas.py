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
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
from pydantic.alias_generators import to_camel

from app.domain.models import FindingType, JobKind, Role

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


class AiShape(InternalSchema):
    """AI 의 `CamelModel` 과 같은 모양 — 파이썬은 snake_case, JSON 은 camelCase.

    필드가 많아 하나하나 alias 를 달지 않고 규칙으로 맞춘다.
    """

    model_config = ConfigDict(alias_generator=to_camel)


class Moment(AiShape):
    """AI `Moment` (`schemas/timeline.py`) — 질문 하나의 타임라인 항목 (#164).

    AI 쪽보다 세게 막지 않는다. 여기서 422 가 나면 그 면접의 결과가 통째로
    버려진다. 저장할 수 없는 값(NUL · 음수 시각)만 거른다.
    """

    moment_id: PgText
    qa_id: PgAnyText
    at_ms: int = Field(ge=0, le=BIGINT_MAX)
    end_ms: int = Field(ge=0, le=BIGINT_MAX)
    label: PgAnyText
    question: PgAnyText
    answer: PgAnyText
    #: 인용 · 발화 id · 시작 ms. BE 는 읽지 않고 그대로 들고 있는다.
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class Finding(AiShape):
    """AI `Finding` (`schemas/analysis.py`) — 근거가 붙은 검토 항목 (#164).

    `state` 는 문자열로 받는다. AI 쪽에는 우리에게 없는 `EDITED` 가 있다 —
    면접관의 판단은 `review_mark` 가 따로 든다(#163).
    """

    finding_id: PgText
    session_id: PgAnyText
    type: FindingType
    competency_id: PgAnyText | None = None
    claim_id: PgAnyText | None = None
    evidence_utterance_id: PgAnyText | None = None
    evidence_quote: PgAnyText | None = None
    evidence_t_ms: int | None = Field(default=None, ge=0, le=BIGINT_MAX)
    summary: PgAnyText
    state: PgAnyText = "PROPOSED"


class ReviewUpsert(AiShape):
    """`PUT /internal/v1/sessions/{sessionId}/review` 의 본문 — 최종 리뷰 결과.

    `status` 는 AI 쪽 `AnalysisResult.status` 를 그대로 받는다. 네 값을 화면의 두
    값(READY · FAILED)으로 줄이는 매핑은 라우터 한 곳에만 둔다 — **Agent 는 무슨
    일이 있었는지를 말하고, 사용자에게 무엇을 보일지는 우리가 정한다.** Agent 쪽에
    번역을 시키면 같은 판단이 두 군데로 갈라진다.

    본문은 AI `ReviewPayload` (`schemas/wire.py`) 다. 요약(`summary` ·
    `keyPoints`)과 타임라인(`moments`) · 검토 항목(`findings`)이 한 번에 온다.
    `status` 는 요약의 것이다 — 요약만 실패해도 나머지는 받는다 (#164).
    """

    status: Literal["completed", "partial", "empty", "failed"]
    summary: PgAnyText = ""
    key_points: list[PgAnyText] = Field(default_factory=list)
    #: 요약이 실패해도 타임라인 · findings 는 따로 나올 수 있다 (#164).
    moments: list[Moment] = Field(default_factory=list)
    #: `None` 은 findings 를 안 돌렸다는 뜻이다 — 키 자체가 없다. 빈 목록
    #: (「찾아봤는데 없다」)과 달라서, 이때는 있던 값을 그대로 둔다.
    findings: list[Finding] | None = None
    #: AI `FindingsResult.status`. `findings` 가 없을 때 그것이 「안 돌림」인지
    #: 「돌렸는데 실패」인지를 가른다 (#244). 목록이 오면 BE 는 목록만 본다.
    findings_status: Literal["completed", "partial", "empty", "failed"] | None = None
    model: PgAnyText = ""
    #: 작업을 받을 때의 `requestedAt` 을 돌려준다. 요약 자리의 요청 시각은 면접
    #: 종료 때 한 번 찍히고 바뀌지 않아 맞춰 볼 일이 없다. 받기만 한다.
    requested_at: str | None = None

    @model_validator(mode="after")
    def _done_means_there_is_something_to_show(self) -> "ReviewUpsert":
        # 본문 없이 READY 로 넘어가면 FE 는 `content` 가 객체라는 이유로 요약
        # 카드를 그리고, 그 안이 비어 있다. 실패로 두는 편이 맞다.
        if self.status in ("completed", "partial") and not self.summary.strip():
            raise ValueError("completed/partial 이면 summary 가 비어 있을 수 없다")
        return self


# ── AI 분석 작업 (#162) ─────────────────────────────────────


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


class ReportStatementUpsert(AiShape):
    """리포트 문장 하나 — AI 가 쓴 한 줄과 그 근거의 id (#238).

    근거 본문(역량 이름 · 지원서 문장 · 면접 발화 · 시각)은 보내지 않는다. BE 가
    `findingId` 로 붙인다 (#163) — 같은 근거가 검토 화면과 리포트에서 다르게 보이면
    안 된다.
    """

    text: PgAnyText
    finding_id: PgText


class ReportCompetencyUpsert(AiShape):
    """역량 하나의 카드. `competencyId` 는 받은 컨텍스트에 있던 것이어야 한다.

    `nextQuestions` 만 근거 없이 온다 — 다음에 물어볼 것은 이 카드의 결론이라
    「근거 없는 문장은 버린다」의 예외다 (#239 와 맞춘 규칙).
    """

    competency_id: PgText
    confirmed: list[ReportStatementUpsert] = Field(default_factory=list)
    unconfirmed: list[ReportStatementUpsert] = Field(default_factory=list)
    next_questions: list[PgAnyText] = Field(default_factory=list)


class ReportUpsert(AiShape):
    """`PUT /internal/v1/interviews/{interviewId}/report` — 리포트 본문 (#238).

    `status` 는 AI 쪽 네 값 그대로다. 화면의 두 값(READY · FAILED)으로 줄이는 매핑은
    라우터 한 곳에만 둔다 — `ReviewUpsert` 와 같은 이유다.

    `requestedAt` 은 받은 작업의 것을 그대로 돌려받는다. 그 사이 면접관이 다시
    눌렀으면 결과를 409 로 거절한다. 시간대가 없으면 저장된 값과 비교할 수 없어
    422 다.
    """

    status: Literal["completed", "partial", "empty", "failed"]
    requested_at: AwareDatetime
    overview: PgAnyText = ""
    model: PgAnyText = ""
    competencies: list[ReportCompetencyUpsert] = Field(default_factory=list)

    @model_validator(mode="after")
    def _done_means_there_is_something_to_show(self) -> "ReportUpsert":
        # 개요 없이 READY 로 넘어가면 FE 는 빈 리포트를 그린다. 「채택한 근거로 쓸
        # 게 없었다」는 `empty` 로 말해야 한다 — 그쪽은 실패 화면이 따로 있다.
        if self.status in ("completed", "partial") and not self.overview.strip():
            raise ValueError("completed/partial 이면 overview 가 비어 있을 수 없다")
        return self


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
