"""Transcript data contract shared by STT ingestion and AI pipelines.

Proposed under issue #6. Field names, millisecond time units, and streaming
merge rules stay provisional until the STT contract review with #7 agrees
on them.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


class Speaker(StrEnum):
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"


class Utterance(BaseModel):
    """One speech segment produced by STT."""

    utterance_id: str
    speaker: Speaker
    text: str
    started_at_ms: int = Field(ge=0)
    ended_at_ms: int = Field(ge=0)
    is_final: bool = True

    @field_validator("utterance_id")
    @classmethod
    def _nonblank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("utterance_id must not be blank")
        return value

    @model_validator(mode="after")
    def _check_time_range(self) -> Self:
        if self.ended_at_ms < self.started_at_ms:
            raise ValueError("ended_at_ms must not precede started_at_ms")
        if self.is_final and not self.text.strip():
            raise ValueError("final utterance text must not be blank")
        return self


class Transcript(BaseModel):
    """Utterances collected for one interview session."""

    session_id: str
    stage: Literal["live", "realigned"] = "live"
    utterances: list[Utterance] = Field(default_factory=list)

    @field_validator("session_id")
    @classmethod
    def _nonblank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("session_id must not be blank")
        return value

    @model_validator(mode="after")
    def _check_revisions(self) -> Self:
        identities: dict[str, tuple[Speaker, int]] = {}
        for utterance in self.utterances:
            identity = (utterance.speaker, utterance.started_at_ms)
            previous = identities.setdefault(utterance.utterance_id, identity)
            if previous != identity:
                raise ValueError("utterance revisions must keep speaker and start time")
        return self

    def final_utterances(self) -> list[Utterance]:
        """Use the last full final revision per ID, then order by start time.

        This is a snapshot contract, not text deltas. A late interim never
        replaces a final. STT final still means provisional when stage is live.
        """

        finals = {u.utterance_id: u for u in self.utterances if u.is_final}
        return sorted(finals.values(), key=lambda u: (u.started_at_ms, u.utterance_id))

    def full_text(self) -> str:
        """Speaker-labelled plain text used as summarization input."""

        return "\n".join(
            f"{u.speaker.value}: {u.text}" for u in self.final_utterances()
        )
