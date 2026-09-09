"""One-shot backend snapshot → Q&A → summary with evidence."""

import asyncio
from time import perf_counter

from irya_ai.pipeline.qa_segmentation import segment_qa
from irya_ai.schemas.summary import AnalysisError, AnalysisResult
from irya_ai.schemas.transcript import (
    SpeakerRole,
    TranscriptSnapshot,
    TranscriptStage,
)
from irya_ai.summarize import SummarizationError, Summarizer


class ContextAnalysisAgent:
    def __init__(self, summarizer: Summarizer, *, timeout_seconds: float = 30) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.summarizer = summarizer
        self.timeout_seconds = timeout_seconds

    async def analyze(self, transcript: TranscriptSnapshot) -> AnalysisResult:
        started = perf_counter()
        finals = transcript.final_utterances()
        segmentation = segment_qa(finals)
        unpaired = [
            utterance.utterance_id
            for utterance, reason in segmentation.dropped
            if reason == "candidate speech before any question"
        ]
        result = AnalysisResult(
            session_id=transcript.session_id,
            transcript_stage=transcript.stage,
            status="empty",
            qa_pairs=segmentation.qa_pairs,
            unpaired_utterance_ids=unpaired,
        )
        if transcript.stage is TranscriptStage.LIVE:
            result.warnings.append("PROVISIONAL_TRANSCRIPT")
        if unpaired:
            result.warnings.append("UNPAIRED_CANDIDATE_UTTERANCES")
        if any(not pair.answer_utterance_ids for pair in segmentation.qa_pairs):
            result.warnings.append("UNANSWERED_QUESTIONS")
        if not any(u.speaker is SpeakerRole.CANDIDATE for u in finals):
            result.warnings.append("NO_FINAL_CANDIDATE_SPEECH")
            result.elapsed_ms = round((perf_counter() - started) * 1000)
            return result

        try:
            async with asyncio.timeout(self.timeout_seconds):
                summary = await self.summarizer.summarize(transcript)
            if summary.session_id != transcript.session_id:
                raise SummarizationError("SUMMARY_SESSION_MISMATCH")
            if not summary.points:
                raise SummarizationError("NO_GROUNDED_SUMMARY")
            result.summary_result = summary
            result.status = "completed"
            if summary.rejected_point_count:
                result.status = "partial"
                result.warnings.append("UNGROUNDED_POINTS_REMOVED")
        except TimeoutError:
            result.status = "failed"
            result.error = AnalysisError(code="LLM_TIMEOUT", retryable=True)
        except SummarizationError as exc:
            result.status = "failed"
            result.error = AnalysisError(code=exc.code, retryable=exc.retryable)
        result.elapsed_ms = round((perf_counter() - started) * 1000)
        return result
