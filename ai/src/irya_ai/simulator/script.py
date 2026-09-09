"""Scripted interview format used as simulator input.

A script is a JSON file with a session id and an ordered list of turns:

    {
      "sessionId": "ses_sample_01",
      "title": "백엔드 신입 모의 면접 1",
      "turns": [
        {"speaker": "INTERVIEWER", "startMs": 0, "endMs": 4200,
         "content": "자기소개 부탁드립니다."},
        {"speaker": "CANDIDATE", "startMs": 4800, "endMs": 21000,
         "content": "안녕하세요, ..."}
      ]
    }

Keys may be camelCase or snake_case. Turns must be ordered by ``start_ms``;
overlaps are allowed to model interruptions.
"""

import json
from pathlib import Path

from pydantic import Field, model_validator

from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.transcript import SpeakerRole


class ScriptTurn(CamelModel):
    """One spoken turn in a scripted interview."""

    speaker: SpeakerRole
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    content: str = Field(min_length=1)
    uncertain: bool = False

    @model_validator(mode="after")
    def _check_range(self) -> "ScriptTurn":
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self


class TranscriptScript(CamelModel):
    """A full scripted interview."""

    session_id: str = Field(examples=["ses_sample_01"])
    title: str
    description: str | None = None
    turns: list[ScriptTurn] = Field(min_length=1)

    @model_validator(mode="after")
    def _turns_are_ordered(self) -> "TranscriptScript":
        for prev, curr in zip(self.turns, self.turns[1:], strict=False):
            if curr.start_ms < prev.start_ms:
                raise ValueError(
                    "turns must be ordered by start_ms "
                    f"({curr.start_ms} follows {prev.start_ms})"
                )
        return self

    @property
    def duration_ms(self) -> int:
        return max(turn.end_ms for turn in self.turns)


def load_script(path: str | Path) -> TranscriptScript:
    """Read and validate a script JSON file."""

    raw = Path(path).read_text(encoding="utf-8")
    return TranscriptScript.model_validate(json.loads(raw))
