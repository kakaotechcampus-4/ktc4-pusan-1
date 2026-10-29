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
``participantId``       *absent* - the worker supplies the human identity
``trackId``             ``track_id``
``seq``                 ``seq``
======================  ==========================================

Renaming ``Utterance`` to close that gap would reach into Q&A segmentation,
the timeline and grounding, all of which read the TechSpec names. So the
translation lives here, at the send boundary, and the pipeline keeps its own
vocabulary. ``CamelModel`` forbids unknown keys, so a drift on either side of
this boundary fails the request instead of dropping a field quietly.

The suggestion payload is the same story from the other end. It renames one
field and drops the pipeline-only fields:

========================  ==========================================
agreed payload            ``SuggestedQuestion``
========================  ==========================================
``suggestionId``          ``question_id``
``content``               ``content``
``evidenceUtteranceIds``  ``evidence_utterance_ids``
*absent*                  ``reason`` ``status`` ``qa_id`` ``asked_at``
========================  ==========================================

``reason`` and ``status`` are not losses: the rationale is for the interviewer
and the status is Backend's to keep once the question is theirs.

The review payload (#220) is assembled rather than renamed: one interview's
summary, timeline and findings come from three agents, and Backend stores
them as one row.

==============  ==============================================================
agreed payload  source
==============  ==============================================================
``status``      ``AnalysisResult.status`` - the summary's, as it stands
``summary``     ``SummaryResult.summary``
``keyPoints``   ``SummaryResult.key_points``
``moments``     ``TimelineResult.moments``
``findings``    ``FindingsResult.findings``; *absent* while findings is not wired
``model``       the model the poller runs
==============  ==============================================================

``status`` is the summary's alone. Backend reads it as the state of the
summary (a ``completed`` or ``partial`` row must carry text, an ``empty`` or
``failed`` one marks the summary failed), so a timeline that failed does not
fail a summary that worked; it arrives as an empty ``moments`` list.

The report payload (#238) is the smallest of the four: sentences and the id
of the adopted finding each rests on. Backend joins the finding's quote, time
and competency name from the id, so the report never carries a quotation
that could drift from the stored one.

==================  ==========================================================
agreed payload      source
==================  ==========================================================
``status``          ``ReportResult.status``; the review vocabulary
``requestedAt``     the job's ``requestedAt``, returned as received
``overview``        ``ReportResult.overview``
``competencies``    ``ReportResult.competencies``; ``{text, findingId}`` items
==================  ==========================================================
"""

from typing import Literal

from pydantic import Field, model_validator

from irya_ai.schemas.analysis import Finding, SuggestedQuestion
from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.report import CompetencyReport, ReportResult
from irya_ai.schemas.summary import AnalysisResult
from irya_ai.schemas.timeline import Moment, TimelineResult
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
    frame is being built. Backend keys on ``(sessionId, stage, utteranceId)`` and
    upserts, so the same payload resent after a reconnect is not a duplicate.
    """

    utterance_id: str = Field(min_length=1, examples=["utt_001"])
    participant_id: str = Field(min_length=1, examples=["candidate_123"])
    track_id: str = Field(min_length=1)
    seq: int = Field(ge=0, le=2**63 - 1)
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

    ``participant_id`` is supplied by the caller. The worker uses the human
    LiveKit identity (INTERVIEWER or CANDIDATE), as specified in #137, never
    the track SID. ``trackId`` and ``seq`` preserve the source ordering for
    persisted-input analysis; the current Backend still ignores these two
    fields until its #137 storage extension is implemented.
    """

    if not utterance.is_final:
        raise ValueError("only FINAL utterances may be sent to Backend")

    return TranscriptPayload(
        utterance_id=utterance.utterance_id,
        participant_id=participant_id,
        track_id=utterance.track_id,
        seq=utterance.seq,
        speaker=utterance.speaker,
        text=utterance.content,
        started_at_ms=utterance.start_ms,
        ended_at_ms=utterance.end_ms,
    )


class SuggestionPayload(CamelModel):
    """One follow-up as ``POST /internal/v1/sessions/{sessionId}/suggestions``.

    This route carries only follow-up questions, so no type discriminator is
    needed. As with the transcript payload the session lives in the path, not
    the body. ``evidenceUtteranceIds`` is required and non-empty on purpose:
    a suggestion that cannot point at what prompted it is the one thing this
    pipeline refuses to produce, and the model enforces that at the boundary.
    """

    suggestion_id: str = Field(min_length=1, examples=["sug_001"])
    content: str = Field(min_length=1)
    evidence_utterance_ids: list[str] = Field(min_length=1, examples=[["utt_001"]])


def suggestion_payload(question: SuggestedQuestion) -> SuggestionPayload:
    """Translate one verified ``SuggestedQuestion`` into the agreed payload.

    ``question_id`` is carried over as ``suggestionId``. Who is supposed to
    issue that id is still open with Backend; the Agent issues the transcript's
    ``utteranceId`` the same way, so it issues this one too until told
    otherwise. If Backend turns out to own it, the fix is one field here rather
    than a change to how suggestions are generated.
    """

    return SuggestionPayload(
        suggestion_id=question.question_id,
        content=question.content,
        evidence_utterance_ids=question.evidence_utterance_ids,
    )


class ReviewPayload(CamelModel):
    """One interview's analysis as ``PUT /internal/v1/sessions/{sessionId}/review``.

    ``findings`` is ``None`` when no findings agent ran, and the key is left
    out of the body then (:meth:`BackendClient.put_review`): an empty list
    would read as "looked and found nothing".
    """

    status: Literal["completed", "partial", "empty", "failed"]
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    moments: list[Moment] = Field(default_factory=list)
    findings: list[Finding] | None = None
    model: str = ""


def review_payload(
    summary: AnalysisResult,
    timeline: TimelineResult | None,
    *,
    findings: list[Finding] | None = None,
    model: str,
) -> ReviewPayload:
    """Fold the three agents' results into the one row Backend stores.

    Backend refuses (422) a ``completed`` or ``partial`` row with no summary
    text, and a refused row is a job stuck at the head of the queue. The
    summary agent does not produce one, but if it ever did the row is sent as
    ``failed`` instead: the summary is missing either way, and this way the
    job leaves the queue.
    """

    result = summary.summary_result
    text = result.summary.strip() if result else ""
    status = summary.status
    if status in ("completed", "partial") and not text:
        status = "failed"
    return ReviewPayload(
        status=status,
        summary=text,
        key_points=list(result.key_points) if result and text else [],
        moments=list(timeline.moments) if timeline else [],
        findings=findings,
        model=model,
    )


class ReportPayload(CamelModel):
    """One interview's report as ``PUT /internal/v1/interviews/{interviewId}/report``.

    ``requestedAt`` goes back exactly as the job carried it: Backend answers
    409 when the report was requested again in the meantime, and that result
    is dropped rather than retried. ``status`` uses the review vocabulary;
    Backend folds ``completed`` and ``partial`` into READY, ``empty`` into
    FAILED with ``NO_EVIDENCE`` and ``failed`` into FAILED (#238).
    """

    status: Literal["completed", "partial", "empty", "failed"]
    requested_at: str
    overview: str = ""
    competencies: list[CompetencyReport] = Field(default_factory=list)


def report_payload(result: ReportResult, *, requested_at: str) -> ReportPayload:
    """The agent's result as the agreed row; nothing but sentences on failure."""

    usable = result.status in ("completed", "partial")
    return ReportPayload(
        status=result.status,
        requested_at=requested_at,
        overview=result.overview if usable else "",
        competencies=list(result.competencies) if usable else [],
    )
