"""Pre-interview preparation: what the LLM drafts and what the pipeline keeps.

Before an interview starts, the job description and the resume are turned into
the two lists everything later hangs on: the competencies the interview should
cover (:class:`~irya_ai.schemas.context.Competency`) and the resume statements
worth checking (:class:`~irya_ai.schemas.context.ResumeClaim`). Follow-up
suggestions read them as context, findings refer to them by id, and Backend
computes coverage from them (#137).

The model writes text only. Identifiers are derived from that text by
:mod:`irya_ai.prep`, never chosen by the model, and a resume claim is kept only
if its ``quote`` occurs in the resume body verbatim - the same rule the
timeline and the live suggestions apply to transcript quotes.
"""

from typing import Literal

from pydantic import Field

from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.context import Competency, ResumeClaim
from irya_ai.schemas.summary import AnalysisError, DraftModel
from irya_ai.schemas.timeline import LlmUsage

# A competency name is a chip on the review screen, not a sentence.
COMPETENCY_NAME_MAX_CHARS = 20
COMPETENCY_DESCRIPTION_MAX_CHARS = 120
# Under ten characters a "quote" is a keyword that matches half the resume;
# over two hundred it is a paragraph nobody verifies against an answer.
CLAIM_QUOTE_MIN_CHARS = 10
CLAIM_QUOTE_MAX_CHARS = 200
# Backend renders this as "지원서 · {section}" (#137), so it is a short label.
CLAIM_SECTION_MAX_CHARS = 20


class CompetencyDraft(DraftModel):
    """One competency as the model names it. Verified before use."""

    name: str
    required: bool
    description: str


class ResumeClaimDraft(DraftModel):
    """One resume statement as the model quotes it. Verified before use.

    ``section`` has no default on purpose: strict structured output wants
    every key present, so "no section" is an explicit ``null``.
    """

    quote: str
    section: str | None


class PrepDraft(DraftModel):
    """Structured-output schema handed to the model. Nothing else is generated."""

    competencies: list[CompetencyDraft]
    resume_claims: list[ResumeClaimDraft]


class PrepResult(CamelModel):
    """One preparation run for one interview.

    ``competencies`` and ``resume_claims`` are the body of
    ``PUT /internal/v1/interviews/{interviewId}/prep`` (#137 2-4) as they
    stand. ``status`` is ``empty`` when there was no job description to read,
    ``partial`` when some drafts were dropped, and ``failed`` when the model
    call failed or nothing usable came back. ``rejections`` says why each
    draft was dropped by position only - never by content, because the
    content is the candidate's resume.
    """

    session_id: str
    status: Literal["completed", "partial", "failed", "empty"]
    competencies: list[Competency] = Field(default_factory=list)
    resume_claims: list[ResumeClaim] = Field(default_factory=list)
    model: str = ""
    rejections: list[str] = Field(
        default_factory=list,
        description="``competency N: reason`` or ``claim N: reason`` per drop.",
    )
    warnings: list[str] = Field(default_factory=list)
    error: AnalysisError | None = None
    usage: LlmUsage | None = None
    elapsed_ms: int = 0
