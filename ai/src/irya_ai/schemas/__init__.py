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
from irya_ai.schemas.transcript import (
    PassType,
    SpeakerRole,
    Track,
    Utterance,
    Word,
)

__all__ = [
    "CamelModel",
    "Candidate",
    "Company",
    "Competency",
    "Finding",
    "FindingState",
    "FindingType",
    "InterviewContext",
    "JobDescription",
    "PassType",
    "QAPair",
    "Resume",
    "ResumeClaim",
    "ReviewReport",
    "ReviewReportStatus",
    "Rubric",
    "SpeakerRole",
    "SuggestedQuestion",
    "SuggestedQuestionStatus",
    "Track",
    "Utterance",
    "Word",
]
