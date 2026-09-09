"""One-shot backend snapshot → Q&A → summary with evidence."""

import asyncio
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field

from irya_ai.qa import QAPair, group_qa
from irya_ai.summarize import SummarizationError, Summarizer, SummaryResult
from irya_ai.transcript import Speaker, Transcript


class AnalysisError(BaseModel):
    code: str
    retryable: bool


class AnalysisResult(BaseModel):
    session_id: str
    transcript_stage: Literal["live", "realigned"]
    status: Literal["completed", "partial", "failed", "empty"]
    qa_pairs: list[QAPair]
    unpaired_utterance_ids: list[str]
    summary_result: SummaryResult | None = None
    warnings: list[str] = Field(default_factory=list)
    error: AnalysisError | None = None
    elapsed_ms: int = 0


class ContextAnalysisAgent:
    def __init__(self, summarizer: Summarizer, *, timeout_seconds: float = 30) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.summarizer = summarizer
        self.timeout_seconds = timeout_seconds

    async def analyze(self, transcript: Transcript) -> AnalysisResult:
        started = perf_counter()
        qa_pairs, unpaired = group_qa(transcript)
        result = AnalysisResult(
            session_id=transcript.session_id,
            transcript_stage=transcript.stage,
            status="empty",
            qa_pairs=qa_pairs,
            unpaired_utterance_ids=unpaired,
        )
        if transcript.stage == "live":
            result.warnings.append("PROVISIONAL_TRANSCRIPT")
        if unpaired:
            result.warnings.append("UNPAIRED_CANDIDATE_UTTERANCES")
        if any(not pair.answer_utterance_ids for pair in qa_pairs):
            result.warnings.append("UNANSWERED_QUESTIONS")
        if not any(
            u.speaker == Speaker.CANDIDATE for u in transcript.final_utterances()
        ):
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
