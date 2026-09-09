"""Transcript models: what the STT layer produces and the analysis layer consumes.

Mirrors the ``TRACK`` / ``UTTERANCE`` / ``WORD`` entities in the TechSpec data
model. Timestamps are milliseconds from the start of the session recording so
they can be used directly for video seek.
"""

from enum import StrEnum

from pydantic import Field, model_validator

from irya_ai.schemas.base import CamelModel


class SpeakerRole(StrEnum):
    """Participant role. Values match the ``role`` field of the join API."""

    INTERVIEWER = "INTERVIEWER"
    CANDIDATE = "CANDIDATE"


class PassType(StrEnum):
    """Which STT pass produced an utterance.

    ``INTERIM`` is a provisional live result that may still change.
    ``FINAL`` is the confirmed text for that utterance.
    """

    INTERIM = "INTERIM"
    FINAL = "FINAL"


class Track(CamelModel):
    """One participant's audio track within a session."""

    track_id: str = Field(examples=["trk_candidate"])
    session_id: str = Field(examples=["ses_123"])
    role: SpeakerRole


class Word(CamelModel):
    """Word-level timing inside an utterance."""

    seq: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    content: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_range(self) -> "Word":
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self


class Utterance(CamelModel):
    """A single continuous speech segment from one speaker.

    ``seq`` orders utterances within a session regardless of speaker.
    ``qa_id`` / ``qa_role`` are filled in by Q&A segmentation, not by STT.
    """

    utterance_id: str = Field(examples=["utt_014"])
    session_id: str = Field(examples=["ses_123"])
    track_id: str = Field(examples=["trk_candidate"])
    speaker: SpeakerRole
    seq: int = Field(ge=0)
    pass_type: PassType = PassType.FINAL
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    content: str = Field(min_length=1)
    uncertain: bool = False
    words: list[Word] = Field(default_factory=list)
    qa_id: str | None = None
    qa_role: str | None = Field(
        default=None,
        description="'QUESTION' or 'ANSWER' once Q&A segmentation has run.",
    )

    @model_validator(mode="after")
    def _check_range(self) -> "Utterance":
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def is_final(self) -> bool:
        return self.pass_type is PassType.FINAL
