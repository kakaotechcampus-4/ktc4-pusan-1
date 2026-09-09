import asyncio

import pytest

from irya_ai.analysis import ContextAnalysisAgent
from irya_ai.qa import group_qa
from irya_ai.summarize import (
    ExtractiveSummarizer,
    FakeSummarizer,
    SummarizationError,
)
from irya_ai.transcript import Transcript, Utterance


def utterance(uid: str, speaker: str, text: str, start: int, **kwargs) -> Utterance:
    return Utterance(
        utterance_id=uid,
        speaker=speaker,
        text=text,
        started_at_ms=start,
        ended_at_ms=start + 10,
        **kwargs,
    )


def test_grouping_handles_fragments_orphans_and_unanswered_question() -> None:
    transcript = Transcript(
        session_id="s",
        utterances=[
            utterance("intro", "candidate", "안녕하세요", 0),
            utterance("q1", "interviewer", "어떤 일을", 10),
            utterance("q2", "interviewer", "하셨나요?", 20),
            utterance("a1", "candidate", "서버를", 30),
            utterance("a2", "candidate", "구현했습니다", 40),
            utterance("q3", "interviewer", "성과는요?", 50),
            utterance("a3", "candidate", "응답 시간을", 60, is_final=False),
        ],
    )

    pairs, unpaired = group_qa(transcript)

    assert unpaired == ["intro"]
    assert len(pairs) == 2
    assert pairs[0].question_utterance_ids == ["q1", "q2"]
    assert pairs[0].answer == "서버를\n구현했습니다"
    assert (pairs[0].started_at_ms, pairs[0].ended_at_ms) == (10, 50)
    assert pairs[1].answer_utterance_ids == []


async def test_offline_analysis_has_source_evidence(
    sample_transcript: Transcript,
) -> None:
    result = await ContextAnalysisAgent(ExtractiveSummarizer()).analyze(
        sample_transcript
    )

    assert result.status == "completed"
    assert len(result.qa_pairs) == 2
    assert result.summary_result.source_utterance_ids == ["u-002", "u-004"]
    assert "40%" in result.summary_result.summary
    assert "Django" in result.summary_result.summary
    assert result.summary_result.points[1].evidence[0].started_at_ms == 15500
    assert "PROVISIONAL_TRANSCRIPT" in result.warnings


async def test_empty_or_interim_input_never_calls_model() -> None:
    class MustNotRun:
        async def summarize(self, transcript):
            pytest.fail("No finalized candidate speech should skip the model")

    agent = ContextAnalysisAgent(MustNotRun())
    for utterances in [[], [utterance("u", "candidate", "", 0, is_final=False)]]:
        result = await agent.analyze(Transcript(session_id="s", utterances=utterances))
        assert result.status == "empty"
        assert result.summary_result is None


async def test_unanswered_question_survives_without_llm() -> None:
    result = await ContextAnalysisAgent(ExtractiveSummarizer()).analyze(
        Transcript(
            session_id="s",
            utterances=[utterance("q", "interviewer", "경험은요?", 0)],
        )
    )
    assert result.status == "empty"
    assert result.qa_pairs[0].question == "경험은요?"
    assert "UNANSWERED_QUESTIONS" in result.warnings


async def test_provider_failure_preserves_qa_and_does_not_poison_next_session(
    sample_transcript: Transcript,
) -> None:
    class FailsOnce(ExtractiveSummarizer):
        calls = 0

        async def summarize(self, transcript):
            self.calls += 1
            if self.calls == 1:
                raise SummarizationError("LLM_UNAVAILABLE", retryable=True)
            return await super().summarize(transcript)

    agent = ContextAnalysisAgent(FailsOnce())
    failed = await agent.analyze(sample_transcript)
    recovered = await agent.analyze(
        sample_transcript.model_copy(
            update={"session_id": "next", "stage": "realigned"}
        )
    )

    assert failed.status == "failed"
    assert failed.error.code == "LLM_UNAVAILABLE"
    assert failed.error.retryable
    assert len(failed.qa_pairs) == 2
    assert failed.summary_result is None
    assert recovered.status == "completed"
    assert recovered.summary_result.session_id == "next"
    assert "PROVISIONAL_TRANSCRIPT" not in recovered.warnings


async def test_agent_timeout_retains_transcript_structure(
    sample_transcript: Transcript,
) -> None:
    class SlowSummarizer:
        async def summarize(self, transcript):
            await asyncio.Event().wait()

    result = await ContextAnalysisAgent(SlowSummarizer(), timeout_seconds=0.01).analyze(
        sample_transcript
    )
    assert result.status == "failed"
    assert result.error.code == "LLM_TIMEOUT"
    assert len(result.qa_pairs) == 2


async def test_preset_fake_is_not_reported_as_grounded_analysis(
    sample_transcript: Transcript,
) -> None:
    result = await ContextAnalysisAgent(FakeSummarizer("상수 요약")).analyze(
        sample_transcript
    )
    assert result.status == "failed"
    assert result.error.code == "NO_GROUNDED_SUMMARY"


async def test_input_changes_result_and_concurrent_sessions_stay_separate(
    sample_transcript: Transcript,
) -> None:
    other = Transcript(
        session_id="other",
        utterances=[utterance("a", "candidate", "디자인 시스템을 만들었습니다.", 0)],
    )
    agent = ContextAnalysisAgent(ExtractiveSummarizer())
    first, second = await asyncio.gather(
        agent.analyze(sample_transcript), agent.analyze(other)
    )
    assert first.summary_result.summary != second.summary_result.summary
    assert second.summary_result.source_utterance_ids == ["a"]
    assert second.unpaired_utterance_ids == ["a"]
    assert "FastAPI" not in second.summary_result.summary
