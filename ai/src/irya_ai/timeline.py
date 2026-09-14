"""Review timeline: chunked transcript -> Q&A -> labelled, evidence-backed moments.

Runs once the interview has ended. The STT layer has been appending one
``Utterance`` per chunk; this module folds them into a ``TranscriptSnapshot``,
groups them into ``QAPair``s with the rule-based segmenter, asks a model for a
short label and a one-line answer summary per question, and keeps only the
moments whose citations really occur in the candidate's utterances.

The model never chooses timestamps or rewrites questions: those are copied
from the ``QAPair``. It only writes ``label``, ``answer`` and the quotes that
back the answer, and a draft that fails any check is dropped whole (the same
policy as ``summarize.ground_summary``).
"""

import asyncio
import re
from collections.abc import Iterable, Mapping
from time import perf_counter
from typing import Protocol, runtime_checkable

from irya_ai.evaluation import unsupported_numbers_in_text
from irya_ai.pipeline.grounding import locate_quote
from irya_ai.pipeline.qa_segmentation import segment_qa
from irya_ai.schemas.analysis import QAPair
from irya_ai.schemas.summary import AnalysisError
from irya_ai.schemas.timeline import (
    LABEL_MAX_CHARS,
    LlmUsage,
    Moment,
    MomentCitationDraft,
    MomentDraft,
    MomentEvidence,
    TimelineDraft,
    TimelineResult,
)
from irya_ai.schemas.transcript import (
    SpeakerRole,
    TranscriptSnapshot,
    TranscriptStage,
    Utterance,
)

# TechSpec: 5-8 markers; above 10 the labels overlap on the timeline.
DEFAULT_MAX_MOMENTS = 8
MIN_MOMENTS_WARNING = 5


class TimelineError(Exception):
    """A safe, structured failure; provider error bodies are never forwarded."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


# --- input -----------------------------------------------------------------


def snapshot_from_chunks(
    chunks: Iterable[Utterance], *, stage: TranscriptStage = TranscriptStage.LIVE
) -> TranscriptSnapshot:
    """Fold the utterances an STT stream appended into one snapshot.

    Every chunk must belong to the same session. Revisions of the same
    ``utterance_id`` are kept; ``TranscriptSnapshot.final_utterances`` picks
    the last FINAL one per ID.
    """

    utterances = list(chunks)
    if not utterances:
        raise ValueError("no utterances")
    session_ids = {u.session_id for u in utterances}
    if len(session_ids) != 1:
        raise ValueError(f"chunks span {len(session_ids)} sessions; expected one")
    return TranscriptSnapshot(
        session_id=utterances[0].session_id, stage=stage, utterances=utterances
    )


# --- selection -------------------------------------------------------------


def select_qa_pairs(
    qa_pairs: Iterable[QAPair], *, max_moments: int = DEFAULT_MAX_MOMENTS
) -> list[QAPair]:
    """Pairs worth a marker: answered ones, at most ``max_moments``.

    When there are too many, the longest answers win (``answer_word_count``),
    on the assumption that a short exchange is a follow-up or small talk.
    The result stays in chronological order so markers read left to right.
    """

    if max_moments < 1:
        raise ValueError("max_moments must be positive")
    answered = [p for p in qa_pairs if p.answer_utterance_ids]
    if len(answered) <= max_moments:
        return answered
    ranked = sorted(answered, key=lambda p: (-p.answer_word_count, p.start_ms))
    chosen = {p.qa_id for p in ranked[:max_moments]}
    return [p for p in answered if p.qa_id in chosen]


# --- verification ----------------------------------------------------------

_COLLAPSE = re.compile(r"\s+")


def _clean_label(label: str) -> str:
    return _COLLAPSE.sub(" ", label).strip()


def _verify_citations(
    citations: list[MomentCitationDraft],
    pair: QAPair,
    sources: Mapping[str, Utterance],
) -> list[MomentEvidence] | str:
    """Evidence for every citation, or the reason the first bad one fails."""

    if not citations:
        return "no citation"
    allowed = set(pair.answer_utterance_ids)
    evidence: list[MomentEvidence] = []
    for c in citations:
        source = sources.get(c.utterance_id)
        if source is None:
            return f"unknown utterance {c.utterance_id}"
        if c.utterance_id not in allowed:
            return f"citation {c.utterance_id} is not part of this answer"
        if source.speaker is not SpeakerRole.CANDIDATE:
            return f"citation {c.utterance_id} is not candidate speech"
        if not c.quote.strip():
            return "empty quote"
        located = locate_quote(c.quote, [source])
        if not located:
            return f"quote not found in {c.utterance_id}"
        evidence.append(
            MomentEvidence(
                utterance_id=c.utterance_id,
                quote=c.quote,
                speaker=source.speaker,
                start_ms=source.start_ms,
                end_ms=source.end_ms,
                t_ms=located[0].t_ms,
            )
        )
    return evidence


def build_timeline(
    snapshot: TranscriptSnapshot,
    selected: list[QAPair],
    draft: TimelineDraft,
    *,
    model: str,
) -> tuple[list[Moment], list[str]]:
    """Turn model drafts into verified moments; report every rejection.

    Returns ``(moments, rejections)``. Moments come back in question order
    regardless of the order the model listed them, and a ``qa_id`` the model
    repeats is used once (first draft wins).
    """

    sources = {u.utterance_id: u for u in snapshot.final_utterances()}
    by_qa = {p.qa_id: p for p in selected}
    moments: dict[str, Moment] = {}
    rejections: list[str] = []

    for d in draft.moments:
        pair = by_qa.get(d.qa_id)
        if pair is None:
            rejections.append(f"{d.qa_id}: not among the selected questions")
            continue
        if d.qa_id in moments:
            rejections.append(f"{d.qa_id}: duplicate draft")
            continue
        label = _clean_label(d.label)
        if not label:
            rejections.append(f"{d.qa_id}: empty label")
            continue
        if len(label) > LABEL_MAX_CHARS:
            rejections.append(f"{d.qa_id}: label longer than {LABEL_MAX_CHARS} chars")
            continue
        answer = d.answer.strip()
        if not answer:
            rejections.append(f"{d.qa_id}: empty answer")
            continue
        verified = _verify_citations(d.citations, pair, sources)
        if isinstance(verified, str):
            rejections.append(f"{d.qa_id}: {verified}")
            continue
        quoted = "\n".join(e.quote for e in verified)
        if numbers := unsupported_numbers_in_text(quoted, answer):
            joined = ", ".join(numbers)
            rejections.append(f"{d.qa_id}: numbers not in evidence: {joined}")
            continue
        moments[d.qa_id] = Moment(
            moment_id=f"mom_{pair.qa_id}",
            qa_id=pair.qa_id,
            at_ms=pair.start_ms,
            end_ms=pair.end_ms,
            label=label,
            question=pair.question_text,
            answer=answer,
            evidence=verified,
        )

    ordered = [moments[p.qa_id] for p in selected if p.qa_id in moments]
    return ordered, rejections


# --- generators ------------------------------------------------------------


@runtime_checkable
class TimelineGenerator(Protocol):
    """Writes the draft. Implementations must not touch timestamps."""

    async def generate(
        self, pairs: list[QAPair], sources: Mapping[str, Utterance]
    ) -> TimelineDraft: ...


_SENTENCE_END = re.compile(r"(?<=[.?!])\s+")


class ExtractiveTimelineGenerator:
    """Offline baseline: first sentence of the answer, quoted verbatim.

    Lets the pipeline run without a key and gives the model a floor to beat.
    """

    async def generate(
        self, pairs: list[QAPair], sources: Mapping[str, Utterance]
    ) -> TimelineDraft:
        drafts: list[MomentDraft] = []
        for pair in pairs:
            first_id = pair.answer_utterance_ids[0]
            source = sources[first_id]
            sentence = _SENTENCE_END.split(source.content.strip(), maxsplit=1)[0]
            drafts.append(
                MomentDraft(
                    qa_id=pair.qa_id,
                    label=_clean_label(pair.question_text)[:LABEL_MAX_CHARS],
                    answer=sentence,
                    citations=[
                        MomentCitationDraft(utterance_id=first_id, quote=sentence)
                    ],
                )
            )
        return TimelineDraft(moments=drafts)


class FakeTimelineGenerator:
    """Test double that returns a preset draft for any input."""

    def __init__(self, draft: TimelineDraft) -> None:
        self.draft = draft
        self.calls: list[list[str]] = []

    async def generate(
        self, pairs: list[QAPair], sources: Mapping[str, Utterance]
    ) -> TimelineDraft:
        self.calls.append([p.qa_id for p in pairs])
        return self.draft


# --- agent -----------------------------------------------------------------


class ReviewTimelineAgent:
    def __init__(
        self,
        generator: TimelineGenerator,
        *,
        model: str = "",
        timeout_seconds: float = 60,
        max_moments: int = DEFAULT_MAX_MOMENTS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.generator = generator
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_moments = max_moments

    async def run(self, snapshot: TranscriptSnapshot) -> TimelineResult:
        started = perf_counter()
        finals = snapshot.final_utterances()
        segmentation = segment_qa(finals)
        selected = select_qa_pairs(segmentation.qa_pairs, max_moments=self.max_moments)
        duration_ms = max((u.end_ms for u in finals), default=0)
        result = TimelineResult(
            session_id=snapshot.session_id,
            transcript_stage=snapshot.stage,
            status="empty",
            duration_ms=duration_ms,
            qa_pairs=segmentation.qa_pairs,
            selected_qa_ids=[p.qa_id for p in selected],
            model=self.model,
        )
        if snapshot.stage is TranscriptStage.LIVE:
            result.warnings.append("PROVISIONAL_TRANSCRIPT")
        unanswered = len(segmentation.qa_pairs) - sum(
            1 for p in segmentation.qa_pairs if p.answer_utterance_ids
        )
        if unanswered:
            result.warnings.append("UNANSWERED_QUESTIONS_SKIPPED")
        if len(segmentation.qa_pairs) - unanswered > self.max_moments:
            result.warnings.append("QUESTIONS_TRUNCATED")
        if not selected:
            result.elapsed_ms = round((perf_counter() - started) * 1000)
            return result

        sources = {u.utterance_id: u for u in finals}
        try:
            async with asyncio.timeout(self.timeout_seconds):
                draft = await self.generator.generate(selected, sources)
        except TimeoutError:
            result.status = "failed"
            result.error = AnalysisError(code="LLM_TIMEOUT", retryable=True)
            result.elapsed_ms = round((perf_counter() - started) * 1000)
            return result
        except TimelineError as exc:
            result.status = "failed"
            result.error = AnalysisError(code=exc.code, retryable=exc.retryable)
            result.elapsed_ms = round((perf_counter() - started) * 1000)
            return result

        usage = getattr(self.generator, "last_usage", None)
        if isinstance(usage, LlmUsage):
            result.usage = usage
        served_model = getattr(self.generator, "last_model", None)
        if served_model:
            result.model = served_model

        moments, rejections = build_timeline(
            snapshot, selected, draft, model=result.model
        )
        result.moments = moments
        result.rejections = rejections
        result.rejected_moment_count = len(rejections)
        missing = len(selected) - len(moments)
        if not moments:
            result.status = "failed"
            result.error = AnalysisError(code="NO_GROUNDED_MOMENTS", retryable=False)
        elif missing:
            result.status = "partial"
            result.warnings.append("UNGROUNDED_MOMENTS_REMOVED")
        else:
            result.status = "completed"
        if moments and len(moments) < MIN_MOMENTS_WARNING:
            result.warnings.append("FEWER_THAN_FIVE_MOMENTS")
        result.elapsed_ms = round((perf_counter() - started) * 1000)
        return result
