"""Interview report (#239): Backend's adopted findings in, sentences out.

The report is the last step of the review flow (TechSpec F10). The
interviewer adopts findings on the review screen, Backend hands the adopted
ones here with the summary and the competencies, and the model writes, per
competency, what was confirmed, what was not, and what to ask next time.
Every sentence names the one adopted finding it rests on; Backend joins the
quote, the time and the competency name from that id (#238), so none of
those are written here.

Input models ignore unknown keys. Backend serves the same finding rows to the
review screen with display fields (``source``, ``atSec``, ``state``) and may
add more; a field this side does not read must not fail the report. The
field names are accepted in the three spellings in play: Backend's review
screen row (``id`` · ``type`` · ``competency`` · ``rationale``), the AI
``Finding`` (``findingId`` · ``type`` · ``competencyId`` · ``summary`` ·
``evidenceQuote``) and the report contract (``findingId`` · ``findingType``
· ``text``).
"""

from typing import Literal

from pydantic import AliasChoices, ConfigDict, Field

from irya_ai.schemas.analysis import FindingType
from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.summary import AnalysisError, DraftModel
from irya_ai.schemas.timeline import LlmUsage

#: One report sentence; the model is told the same limit.
SENTENCE_MAX_CHARS = 200
#: One question for the next interview.
QUESTION_MAX_CHARS = 120
#: Three or four lines about the whole interview.
OVERVIEW_MAX_CHARS = 600
#: Per competency, per list. Keeps a full report inside the gateway's
#: 2,000-token answer cap together with the competencies-per-call split in
#: :mod:`irya_ai.openai_report`.
MAX_SENTENCES_PER_LIST = 4
MAX_NEXT_QUESTIONS = 3


class ReportInput(CamelModel):
    """What Backend sends. Unknown keys are ignored rather than refused."""

    model_config = ConfigDict(extra="ignore")


class ReportSummary(ReportInput):
    """The stored post-interview summary, as context for the overview."""

    overview: str = ""
    key_points: list[str] = Field(default_factory=list)


class ReportCompetency(ReportInput):
    competency_id: str = Field(
        validation_alias=AliasChoices("competencyId", "competency_id", "id")
    )
    name: str
    required: bool = True
    #: Backend's coverage state (``CONFIRMED`` · ``PARTIAL`` · ``MISSING``),
    #: passed to the model as a hint. Backend joins the real value itself.
    state: str | None = None


class AdoptedFinding(ReportInput):
    """One finding the interviewer adopted. The only ground a sentence may cite."""

    finding_id: str = Field(
        validation_alias=AliasChoices("findingId", "finding_id", "id")
    )
    competency_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("competencyId", "competency_id", "competency"),
    )
    finding_type: FindingType = Field(
        validation_alias=AliasChoices("findingType", "finding_type", "type")
    )
    #: The finding's own neutral sentence.
    text: str = Field(validation_alias=AliasChoices("text", "rationale", "summary"))
    #: The resume sentence behind a claim finding, if any.
    quote: str | None = None
    #: The candidate utterance the finding cites, if any.
    transcript: str | None = Field(
        default=None,
        validation_alias=AliasChoices("transcript", "evidenceQuote", "evidence_quote"),
    )


class ReportContext(ReportInput):
    """``GET /internal/v1/interviews/{interviewId}/report/context`` (#238).

    ``findings`` holds adopted findings only; the memo is never part of it.
    """

    interview_id: str
    session_id: str = ""
    summary: ReportSummary = Field(default_factory=ReportSummary)
    competencies: list[ReportCompetency] = Field(default_factory=list)
    findings: list[AdoptedFinding] = Field(default_factory=list)


class SentenceDraft(DraftModel):
    text: str
    finding_id: str


class CompetencyReportDraft(DraftModel):
    competency_id: str
    confirmed: list[SentenceDraft]
    unconfirmed: list[SentenceDraft]
    next_questions: list[str]


class ReportDraft(DraftModel):
    """What the model writes: sentences with the id of the finding each rests on."""

    overview: str
    competencies: list[CompetencyReportDraft]


class ReportSentence(CamelModel):
    """A sentence and the adopted finding behind it; Backend joins the rest."""

    text: str
    finding_id: str


class CompetencyReport(CamelModel):
    competency_id: str
    confirmed: list[ReportSentence] = Field(default_factory=list)
    unconfirmed: list[ReportSentence] = Field(default_factory=list)
    next_questions: list[str] = Field(default_factory=list)

    @property
    def sentence_count(self) -> int:
        return len(self.confirmed) + len(self.unconfirmed)


class ReportResult(CamelModel):
    interview_id: str
    status: Literal["completed", "partial", "empty", "failed"]
    overview: str = ""
    competencies: list[CompetencyReport] = Field(default_factory=list)
    model: str = ""
    rejections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: AnalysisError | None = None
    usage: LlmUsage | None = None
    elapsed_ms: int = 0

    @property
    def sentence_count(self) -> int:
        return sum(c.sentence_count for c in self.competencies)
