"""Analysis outputs: Q&A pairs, findings, suggested questions.

Mirrors the ``QA_PAIR`` / ``FINDING`` / ``SUGGESTED_QUESTION`` entities in the
TechSpec data model. The interview report is not a stored entity on this side:
its wire shape is :class:`irya_ai.schemas.wire.ReportPayload` and its inputs
and results live in :mod:`irya_ai.schemas.report` (#239).

Every ``Finding`` must cite a verbatim ``evidence_quote`` that exists in the
transcript. The grounding check that enforces this lives in the pipeline, not
here, but the contract is: a finding without transcript evidence is invalid.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from irya_ai.schemas.base import CamelModel


class QAPair(CamelModel):
    """One question from the interviewer and the candidate's answer to it."""

    qa_id: str = Field(examples=["qa_003"])
    session_id: str
    question_utterance_ids: list[str] = Field(min_length=1)
    answer_utterance_ids: list[str] = Field(default_factory=list)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    answer_word_count: int = Field(default=0, ge=0)
    question_text: str
    answer_text: str = ""

    @model_validator(mode="after")
    def _check_range(self) -> "QAPair":
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self


class FindingType(StrEnum):
    """What kind of evidence a finding represents."""

    COMPETENCY_EVIDENCE = "COMPETENCY_EVIDENCE"
    CLAIM_VERIFIED = "CLAIM_VERIFIED"
    CLAIM_CONTRADICTED = "CLAIM_CONTRADICTED"
    CLAIM_UNVERIFIED = "CLAIM_UNVERIFIED"
    GAP = "GAP"


class FindingState(StrEnum):
    """Human review state. The agent only ever produces ``PROPOSED``."""

    PROPOSED = "PROPOSED"
    ADOPTED = "ADOPTED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"


class Finding(CamelModel):
    """A structured, evidence-backed observation for the interviewer to review."""

    finding_id: str = Field(examples=["fnd_001"])
    session_id: str
    type: FindingType
    competency_id: str | None = None
    claim_id: str | None = None
    evidence_utterance_id: str | None = None
    evidence_quote: str | None = Field(
        default=None,
        description="Verbatim substring of the cited utterance.",
    )
    evidence_t_ms: int | None = Field(default=None, ge=0)
    summary: str = Field(description="One-sentence, neutral description.")
    state: FindingState = FindingState.PROPOSED

    @model_validator(mode="after")
    def _evidence_is_complete(self) -> "Finding":
        has_quote = self.evidence_quote is not None
        has_source = self.evidence_utterance_id is not None
        if has_quote != has_source:
            raise ValueError(
                "evidence_quote and evidence_utterance_id must be set together"
            )
        if self.type is not FindingType.GAP and not has_quote:
            raise ValueError(f"finding of type {self.type} requires evidence")
        return self


class SuggestedQuestionStatus(StrEnum):
    BUFFERED = "BUFFERED"
    SHOWN = "SHOWN"
    ASKED = "ASKED"
    DISMISSED = "DISMISSED"


class SuggestedQuestion(CamelModel):
    """A follow-up question the agent buffered for the interviewer to consider."""

    question_id: str = Field(examples=["sug_02"])
    session_id: str
    finding_id: str | None = None
    qa_id: str | None = None
    content: str
    reason: str = Field(description="Short rationale shown next to the question.")
    evidence_utterance_ids: list[str] = Field(
        default_factory=list,
        description="Candidate utterances the question follows up on, verified.",
    )
    status: SuggestedQuestionStatus = SuggestedQuestionStatus.BUFFERED
    generated_at: datetime
    asked_at: datetime | None = None
