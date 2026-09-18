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

The suggestion payload is the same story from the other end. It renames one
field, adds one the pipeline has no use for, and drops four:

========================  ==========================================
agreed payload            ``SuggestedQuestion``
========================  ==========================================
``suggestionId``          ``question_id``
``type``                  *absent* - see :class:`SuggestionType`
``content``               ``content``
``evidenceUtteranceIds``  ``evidence_utterance_ids``
*absent*                  ``reason`` ``status`` ``qa_id`` ``asked_at``
========================  ==========================================

``reason`` and ``status`` are not losses: the rationale is for the interviewer
and the status is Backend's to keep once the question is theirs.
"""

from enum import StrEnum

from pydantic import Field, model_validator

from irya_ai.schemas.analysis import SuggestedQuestion
from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.transcript import SpeakerRole, Utterance


class TranscriptPayload(CamelModel):
    """One utterance as a frame on ``WS .../sessions/{sessionId}/transcripts``.

    The session is in the path, not the body, so ``session_id`` is deliberately
    not a field: repeating it here would let a payload disagree with the URL it
    was sent to.

    The frame the Agent writes is this payload plus ``"type":
    "transcript.upsert"``. The discriminator is not a field here either, for
    the same reason the session is not: it identifies the frame, not the
    utterance, and :mod:`irya_ai.transcripts` is the one place that knows a
    frame is being built. Backend keys on ``(sessionId, utteranceId)`` and
    upserts, so the same payload resent after a reconnect is not a duplicate.
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


class SuggestionType(StrEnum):
    """What kind of suggestion this is.

    The agreed payload carries ``type`` and the meeting only ever showed
    ``FOLLOW_UP``. Whether other values exist, and whether the Agent or
    Backend decides them, is not settled - so the enum lives out here at the
    boundary rather than in the pipeline's own vocabulary, and a value added
    later touches this file alone.
    """

    FOLLOW_UP = "FOLLOW_UP"


class SuggestionPayload(CamelModel):
    """One follow-up as ``POST /internal/v1/sessions/{sessionId}/suggestions``.

    As with the transcript payload the session lives in the path, not the body.
    ``evidenceUtteranceIds`` is required and non-empty on purpose: a suggestion
    that cannot point at what prompted it is the one thing this pipeline
    refuses to produce, and the type should say so at the boundary too.
    """

    suggestion_id: str = Field(min_length=1, examples=["sug_001"])
    type: SuggestionType = SuggestionType.FOLLOW_UP
    content: str = Field(min_length=1)
    evidence_utterance_ids: list[str] = Field(min_length=1, examples=[["utt_001"]])


def suggestion_payload(
    question: SuggestedQuestion,
    *,
    suggestion_type: SuggestionType = SuggestionType.FOLLOW_UP,
) -> SuggestionPayload:
    """Translate one verified ``SuggestedQuestion`` into the agreed payload.

    ``question_id`` is carried over as ``suggestionId``. Who is supposed to
    issue that id is still open with Backend; the Agent issues the transcript's
    ``utteranceId`` the same way, so it issues this one too until told
    otherwise. If Backend turns out to own it, the fix is one field here rather
    than a change to how suggestions are generated.
    """

    return SuggestionPayload(
        suggestion_id=question.question_id,
        type=suggestion_type,
        content=question.content,
        evidence_utterance_ids=question.evidence_utterance_ids,
    )
