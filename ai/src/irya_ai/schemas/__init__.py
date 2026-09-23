"""Pydantic models that define the AI pipeline's input and output contracts.

Field names follow the TechSpec data model (snake_case). Every model also
accepts and emits camelCase keys so the same objects can cross the REST /
WebSocket boundary without a second mapping layer.

``wire`` is the one exception: the ``/internal/v1`` contract agreed with
Backend renames several transcript fields rather than only re-casing them, so
that boundary gets explicit payload models instead of a shared one.
"""

from irya_ai.schemas.analysis import (
    Finding,
    FindingState,
    FindingType,
    QAPair,
    ReviewReport,
    ReviewReportStatus,
    SuggestedQuestion,
    SuggestedQuestionStatus,
)
from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.context import (
    Candidate,
    Company,
    Competency,
    InterviewContext,
    JobDescription,
    Resume,
    ResumeClaim,
    Rubric,
)
from irya_ai.schemas.suggestion import (
    SuggestionBatchDraft,
    SuggestionDraft,
    SuggestionResult,
)
from irya_ai.schemas.summary import (
    AnalysisError,
    AnalysisResult,
    CitationDraft,
    Evidence,
    PointDraft,
    SummaryDraft,
    SummaryPoint,
    SummaryResult,
)
from irya_ai.schemas.timeline import (
    LlmUsage,
    Moment,
    MomentCitationDraft,
    MomentDraft,
    MomentEvidence,
    TimelineDraft,
    TimelineResult,
)
from irya_ai.schemas.transcript import (
    PassType,
    SpeakerRole,
    Track,
    TranscriptSnapshot,
    TranscriptStage,
    Utterance,
    Word,
)
from irya_ai.schemas.wire import (
    SuggestionPayload,
    SuggestionType,
    TranscriptPayload,
    suggestion_payload,
    transcript_payload,
)

__all__ = [
    "CamelModel",
    "AnalysisError",
    "AnalysisResult",
    "Candidate",
    "CitationDraft",
    "Company",
    "Competency",
    "Finding",
    "FindingState",
    "FindingType",
    "Evidence",
    "InterviewContext",
    "JobDescription",
    "LlmUsage",
    "Moment",
    "MomentCitationDraft",
    "MomentDraft",
    "MomentEvidence",
    "PassType",
    "PointDraft",
    "QAPair",
    "Resume",
    "ResumeClaim",
    "ReviewReport",
    "ReviewReportStatus",
    "Rubric",
    "SpeakerRole",
    "SuggestedQuestion",
    "SuggestedQuestionStatus",
    "SuggestionBatchDraft",
    "SuggestionDraft",
    "SuggestionPayload",
    "SuggestionResult",
    "SuggestionType",
    "SummaryDraft",
    "SummaryPoint",
    "SummaryResult",
    "TimelineDraft",
    "TimelineResult",
    "Track",
    "TranscriptPayload",
    "TranscriptSnapshot",
    "TranscriptStage",
    "Utterance",
    "Word",
    "suggestion_payload",
    "transcript_payload",
]
