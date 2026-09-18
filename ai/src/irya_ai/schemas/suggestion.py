"""Live follow-up suggestions: what the LLM drafts and what the interviewer sees.

Feeds the in-interview panel (TechSpec F5). While the interview is running the
agent watches the open Q&A and, once the candidate has said enough to follow up
on, asks a model for one or two questions the interviewer could ask next.

The model writes ``content`` and ``reason`` only. Which utterances back a
suggestion it must *cite*, and each citation carries a ``quote`` so the claim
can be checked against the transcript before anything is shown or sent. The
quote is a gate, not an output: the agreed Backend payload carries utterance
ids alone, so a verified quote is dropped once it has done its job, and a
suggestion whose quote is not in the utterance it cites is dropped whole.
"""

from typing import Literal

from pydantic import Field

from irya_ai.schemas.analysis import SuggestedQuestion
from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.summary import AnalysisError, CitationDraft, DraftModel
from irya_ai.schemas.timeline import LlmUsage

# The panel sits beside a live interview, so a suggestion has to be readable
# at a glance - roughly one line of Korean.
CONTENT_MAX_CHARS = 120
REASON_MAX_CHARS = 80


class SuggestionDraft(DraftModel):
    """One follow-up question as the model writes it. Verified before use."""

    content: str
    reason: str
    evidence: list[CitationDraft]


class SuggestionBatchDraft(DraftModel):
    """Structured-output schema handed to the model. Nothing else is generated."""

    suggestions: list[SuggestionDraft]


class SuggestionResult(CamelModel):
    """One analysis round: what came back for a single open Q&A.

    ``status`` is ``empty`` when the model offered nothing and ``partial`` when
    some drafts were dropped for lack of grounding. ``rejections`` keeps the
    reason for every drop so a run can be audited without the drafts
    themselves.
    """

    session_id: str
    qa_id: str
    status: Literal["completed", "partial", "failed", "empty"]
    suggestions: list[SuggestedQuestion] = Field(default_factory=list)
    model: str = ""
    rejections: list[str] = Field(
        default_factory=list, description="One ``reason`` per dropped draft."
    )
    warnings: list[str] = Field(default_factory=list)
    error: AnalysisError | None = None
    usage: LlmUsage | None = None
    elapsed_ms: int = 0
