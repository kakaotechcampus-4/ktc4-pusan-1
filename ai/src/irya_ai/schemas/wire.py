"""The ``/internal/v1`` payloads, spelled the way Backend and Agent agreed them.

Every other model here follows the TechSpec data model and crosses the wire by
case alone, which is why :mod:`irya_ai.schemas` says no second mapping layer is
needed. The internal API is the exception: the agreed transcript payload does
not just re-case :class:`~irya_ai.schemas.transcript.Utterance`, it renames
three of its fields and asks for one it does not carry.

======================  ==========================================
agreed payload          ``Utterance``
======================  ==========================================
``text``                ``content``
``startedAtMs``         ``start_ms``
``endedAtMs``           ``end_ms``
``participantId``       *absent* - the Agent holds ``track_id``
======================  ==========================================

Renaming ``Utterance`` to close that gap would reach into Q&A segmentation,
the timeline and grounding, all of which read the TechSpec names. So the
translation lives here, at the send boundary, and the pipeline keeps its own
vocabulary. ``CamelModel`` forbids unknown keys, so a drift on either side of
this boundary fails the request instead of dropping a field quietly.
"""

from pydantic import Field, model_validator

from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.transcript import SpeakerRole, Utterance


class TranscriptPayload(CamelModel):
    """One utterance as ``POST /internal/v1/sessions/{sessionId}/transcripts``.

    The session is in the path, not the body, so ``session_id`` is deliberately
    not a field: repeating it here would let a payload disagree with the URL it
    was sent to.
    """

    utterance_id: str = Field(min_length=1, examples=["utt_001"])
    participant_id: str = Field(min_length=1, examples=["candidate_123"])
    speaker: SpeakerRole
    text: str = Field(min_length=1)
    started_at_ms: int = Field(ge=0, examples=[15200])
    ended_at_ms: int = Field(ge=0, examples=[23800])

    @model_validator(mode="after")
    def _check_range(self) -> "TranscriptPayload":
        if self.ended_at_ms < self.started_at_ms:
            raise ValueError("endedAtMs must not precede startedAtMs")
        return self


def transcript_payload(
    utterance: Utterance, *, participant_id: str
) -> TranscriptPayload:
    """Translate one ``Utterance`` into the agreed transcript payload.

    ``participant_id`` is a required argument rather than something read off
    the utterance because the Agent genuinely does not have it. What it holds
    is the LiveKit ``track_id``, which is not the Backend's participant
    identifier, and inventing a mapping here would put a wrong id on every
    utterance of the interview while every value still looked well formed.
    Where the caller gets it from is still open with Backend; until it is
    settled, the type system asks for it at every call site.
    """

    return TranscriptPayload(
        utterance_id=utterance.utterance_id,
        participant_id=participant_id,
        speaker=utterance.speaker,
        text=utterance.content,
        started_at_ms=utterance.start_ms,
        ended_at_ms=utterance.end_ms,
    )
