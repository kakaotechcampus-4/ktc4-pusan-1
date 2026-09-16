"""Review-timeline contract: what the LLM drafts and what the review screen gets.

Feeds the interview record screen (TechSpec S3 / F7). The frontend renders one
``Moment`` per interviewer question: a marker on the timeline at ``at_ms``, a
short ``label`` under it, and the question with a one-line answer summary.

Only ``label`` and ``answer`` (plus the citations that back the answer) come
from the model. Timestamps, question text and identifiers are copied from the
rule-based ``QAPair`` so the model can never move a marker or reword a question.
"""

from typing import Literal

from pydantic import Field

from irya_ai.schemas.analysis import QAPair
from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.summary import AnalysisError, DraftModel, Evidence
from irya_ai.schemas.transcript import TranscriptStage

LABEL_MAX_CHARS = 12


class MomentCitationDraft(DraftModel):
    utterance_id: str
    quote: str


class MomentDraft(DraftModel):
    """One question as the model describes it. Verified before display."""

    qa_id: str
    label: str
    answer: str
    citations: list[MomentCitationDraft]


class TimelineDraft(DraftModel):
    """Structured-output schema handed to the model. Nothing else is generated."""

    moments: list[MomentDraft]


class MomentEvidence(Evidence):
    """A verified quote plus where in the utterance it starts."""

    t_ms: int


class Moment(CamelModel):
    """A verified timeline entry. Mirrors the frontend ``Moment`` type in ms."""

    moment_id: str = Field(examples=["mom_qa_utt_003"])
    qa_id: str
    at_ms: int = Field(ge=0, description="Question start; the marker position.")
    end_ms: int = Field(ge=0, description="End of the answer.")
    label: str = Field(min_length=1, max_length=LABEL_MAX_CHARS)
    question: str = Field(description="Interviewer's words, verbatim from QAPair.")
    answer: str = Field(min_length=1, description="Model's one-line summary.")
    evidence: list[MomentEvidence] = Field(min_length=1)

    def to_frontend(self) -> dict[str, object]:
        """The exact shape ``frontend/src/types/interview.ts`` ``Moment`` expects."""

        return {
            "id": self.moment_id,
            "atSec": self.at_ms / 1000,
            "label": self.label,
            "question": self.question,
            "answer": self.answer,
        }


class LlmUsage(CamelModel):
    """Token counts reported by the provider; what the call is billed on."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0


class TimelineResult(CamelModel):
    session_id: str
    transcript_stage: TranscriptStage
    status: Literal["completed", "partial", "failed", "empty"]
    duration_ms: int = Field(ge=0)
    qa_pairs: list[QAPair] = Field(description="Every pair found, before selection.")
    selected_qa_ids: list[str] = Field(
        default_factory=list, description="Pairs offered to the model, in order."
    )
    moments: list[Moment] = Field(default_factory=list)
    model: str = ""
    rejected_moment_count: int = 0
    rejections: list[str] = Field(
        default_factory=list, description="``qa_id: reason`` for each dropped draft."
    )
    warnings: list[str] = Field(default_factory=list)
    error: AnalysisError | None = None
    usage: LlmUsage | None = None
    elapsed_ms: int = 0

    def frontend_moments(self) -> list[dict[str, object]]:
        return [m.to_frontend() for m in self.moments]
