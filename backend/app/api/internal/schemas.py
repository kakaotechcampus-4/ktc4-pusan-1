"""`/internal/v1` 의 요청 모델 — Agent 가 보내는 것.

`app/schemas.py` 와 나눠 둔다. 저쪽은 브라우저가 보는 공개 명세고 이건 Agent 와
우리 사이의 내부 계약이라, 한 파일에 섞이면 어느 쪽을 바꿔도 되는지가 흐려진다.

필드 이름은 Agent 가 보내는 그대로다 (`irya_ai.schemas.wire`). 검증을 세게 걸어
둔 곳이 둘 있다.

* `evidenceUtteranceIds` 는 **비어 있을 수 없다.** 근거를 못 대는 꼬리질문은
  만들지 않는 것이 AI 쪽 파이프라인의 원칙이고, 경계에서도 그걸 말한다.
* `endedAtMs` 는 `startedAtMs` 보다 앞설 수 없다. Agent 쪽 `Utterance` 가 같은
  검증을 갖고 있어 여기서도 같이 막아 둔다.
"""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import Role

FRAME_UPSERT: Final = "transcript.upsert"
FRAME_ACK: Final = "transcript.ack"


class InternalSchema(BaseModel):
    # 모르는 필드는 거절한다. Agent 가 계약에 없는 것을 보내기 시작하면
    # 조용히 버려지는 대신 여기서 드러나야 한다.
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TranscriptUpsert(InternalSchema):
    """`WS /internal/v1/sessions/{sessionId}/transcripts` 의 프레임 하나.

    세션은 경로에 있고 본문에 없다. 본문에도 넣으면 URL 과 다른 값이 실려올 수
    있고, 그때 어느 쪽을 믿을지가 또 규칙이 된다.
    """

    type: Literal["transcript.upsert"]
    utterance_id: str = Field(alias="utteranceId", min_length=1)
    participant_id: str = Field(alias="participantId", min_length=1)
    speaker: Role
    text: str = Field(min_length=1)
    started_at_ms: int = Field(alias="startedAtMs", ge=0)
    ended_at_ms: int = Field(alias="endedAtMs", ge=0)

    @model_validator(mode="after")
    def _check_range(self) -> "TranscriptUpsert":
        if self.ended_at_ms < self.started_at_ms:
            raise ValueError("endedAtMs must be >= startedAtMs")
        return self


class TranscriptAck(InternalSchema):
    """받았다는 답. Agent 는 이걸 받아야 버퍼에서 발화를 지운다."""

    type: Literal["transcript.ack"] = FRAME_ACK
    utterance_id: str = Field(serialization_alias="utteranceId")


class SuggestionCreate(InternalSchema):
    """`POST /internal/v1/sessions/{sessionId}/suggestions` 의 본문."""

    suggestion_id: str = Field(alias="suggestionId", min_length=1)
    type: str = Field(default="FOLLOW_UP", min_length=1)
    content: str = Field(min_length=1)
    evidence_utterance_ids: list[str] = Field(
        alias="evidenceUtteranceIds", min_length=1
    )
