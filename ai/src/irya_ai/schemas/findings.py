"""Model drafts and verified findings; existing Finding remains the wire model."""

from typing import Literal

from pydantic import Field

from irya_ai.schemas.analysis import Finding, FindingType
from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.summary import AnalysisError, DraftModel
from irya_ai.schemas.timeline import LlmUsage
from irya_ai.schemas.transcript import TranscriptStage

SUMMARY_MAX_CHARS = 120


class FindingDraft(DraftModel):
    type: FindingType
    competency_id: str | None
    claim_id: str | None
    evidence_utterance_id: str | None
    evidence_quote: str | None
    summary: str


class FindingsDraft(DraftModel):
    findings: list[FindingDraft]


class FindingsResult(CamelModel):
    session_id: str
    transcript_stage: TranscriptStage
    status: Literal["completed", "partial", "failed", "empty"]
    findings: list[Finding] = Field(default_factory=list)
    model: str = ""
    rejections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: AnalysisError | None = None
    usage: LlmUsage | None = None
    elapsed_ms: int = 0
