"""Pydantic models that define the AI pipeline's input and output contracts.

Field names follow the TechSpec data model (snake_case). Every model also
accepts and emits camelCase keys so the same objects can cross the REST /
WebSocket boundary without a second mapping layer.
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
from irya_ai.schemas.transcript import (
    PassType,
    SpeakerRole,
    Track,
    TranscriptSnapshot,
    TranscriptStage,
    Utterance,
    Word,
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
    "SummaryDraft",
    "SummaryPoint",
    "SummaryResult",
    "Track",
    "TranscriptSnapshot",
    "TranscriptStage",
    "Utterance",
    "Word",
]
