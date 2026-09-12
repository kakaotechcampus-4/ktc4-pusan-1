"""Summary contract and evidence grounding for conversation-context analysis."""

from typing import Protocol, runtime_checkable

from irya_ai.evaluation import unsupported_numbers_in_text
from irya_ai.pipeline.grounding import locate_quote
from irya_ai.schemas.summary import (
    CitationDraft,
    Evidence,
    PointDraft,
    SummaryDraft,
    SummaryPoint,
    SummaryResult,
)
from irya_ai.schemas.transcript import SpeakerRole, TranscriptSnapshot


class SummarizationError(Exception):
    """A safe, structured failure; do not forward provider error bodies."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def ground_summary(
    transcript: TranscriptSnapshot, draft: SummaryDraft, *, model: str
) -> SummaryResult:
    """Drop whole claims with invalid citations; derive all display text.

    Exact quotations and number checks are mechanical checks, not proof that
    a paraphrase is entailed by its evidence. Human review is still required.
    """
    sources = {u.utterance_id: u for u in transcript.final_utterances()}
    points: list[SummaryPoint] = []
    rejected = 0
    for point in draft.points:
        evidence: list[Evidence] = []
        valid = bool(point.text.strip() and point.citations)
        for citation in point.citations:
            source = sources.get(citation.utterance_id)
            if (
                source is None
                or source.speaker is not SpeakerRole.CANDIDATE
                or not citation.quote.strip()
                or not locate_quote(citation.quote, [source])
            ):
                valid = False
                break
            evidence.append(
                Evidence(
                    **citation.model_dump(),
                    speaker=source.speaker,
                    start_ms=source.start_ms,
                    end_ms=source.end_ms,
                )
            )
        if valid:
            valid = not unsupported_numbers_in_text(
                "\n".join(e.quote for e in evidence), point.text
            )
        if valid:
            points.append(SummaryPoint(text=point.text, evidence=evidence))
        else:
            rejected += 1

    return SummaryResult(
        session_id=transcript.session_id,
        summary="\n".join(point.text for point in points),
        key_points=[point.text for point in points],
        source_utterance_ids=list(
            dict.fromkeys(e.utterance_id for p in points for e in p.evidence)
        ),
        model=model,
        points=points,
        rejected_point_count=rejected,
    )


@runtime_checkable
class Summarizer(Protocol):
    async def summarize(self, transcript: TranscriptSnapshot) -> SummaryResult: ...


class ExtractiveSummarizer:
    """Offline baseline: return candidate speech verbatim, without an LLM."""

    async def summarize(self, transcript: TranscriptSnapshot) -> SummaryResult:
        draft = SummaryDraft(
            points=[
                PointDraft(
                    text=u.content,
                    citations=[
                        CitationDraft(utterance_id=u.utterance_id, quote=u.content)
                    ],
                )
                for u in transcript.final_utterances()
                if u.speaker is SpeakerRole.CANDIDATE
            ]
        )
        return ground_summary(transcript, draft, model="extractive-baseline")


class FakeSummarizer:
    """Test double that returns a preset summary for any transcript."""

    def __init__(self, summary: str, key_points: list[str] | None = None) -> None:
        self._summary = summary
        self._key_points = key_points or []

    async def summarize(self, transcript: TranscriptSnapshot) -> SummaryResult:
        return SummaryResult(
            session_id=transcript.session_id,
            summary=self._summary,
            key_points=self._key_points,
            source_utterance_ids=[
                u.utterance_id for u in transcript.final_utterances()
            ],
            model="fake",
        )
