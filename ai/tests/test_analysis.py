import asyncio

import pytest

from irya_ai.analysis import ContextAnalysisAgent
from irya_ai.schemas import (
    SpeakerRole,
    TranscriptSnapshot,
    TranscriptStage,
    Utterance,
)
from irya_ai.summarize import (
    ExtractiveSummarizer,
    FakeSummarizer,
    SummarizationError,
)


def utterance(uid: str, speaker: str, text: str, seq: int, **kwargs) -> Utterance:
    role = SpeakerRole(speaker)
    return Utterance(
        utterance_id=uid,
        session_id="s",
        track_id=f"trk_{role.value.lower()}",
        speaker=role,
        seq=seq,
        content=text,
        start_ms=seq * 10,
        end_ms=seq * 10 + 9,
        **kwargs,
    )


async def test_offline_analysis_has_source_evidence(
    sample_transcript: TranscriptSnapshot,
) -> None:
    result = await ContextAnalysisAgent(ExtractiveSummarizer()).analyze(
        sample_transcript
    )

    assert result.status == "completed"
    assert len(result.qa_pairs) == 2
    assert result.summary_result.source_utterance_ids == ["u-002", "u-004"]
    assert "40%" in result.summary_result.summary
    assert "Django" in result.summary_result.summary
    assert result.summary_result.points[1].evidence[0].start_ms == 15500
    assert "PROVISIONAL_TRANSCRIPT" in result.warnings


async def test_orphans_and_unanswered_question_are_preserved() -> None:
    snapshot = TranscriptSnapshot(
        session_id="s",
        utterances=[
            utterance("intro", "CANDIDATE", "안녕하세요", 0),
            utterance("q1", "INTERVIEWER", "어떤 일을", 1),
            utterance("q2", "INTERVIEWER", "하셨나요?", 2),
            utterance("a1", "CANDIDATE", "서버를", 3),
            utterance("a2", "CANDIDATE", "구현했습니다", 4),
            utterance("q3", "INTERVIEWER", "성과는요?", 5),
        ],
    )

    result = await ContextAnalysisAgent(ExtractiveSummarizer()).analyze(snapshot)

    assert result.unpaired_utterance_ids == ["intro"]
    assert len(result.qa_pairs) == 2
    assert result.qa_pairs[0].question_utterance_ids == ["q1", "q2"]
    assert result.qa_pairs[0].answer_text == "서버를 구현했습니다"
    assert result.qa_pairs[1].answer_utterance_ids == []
    assert "UNANSWERED_QUESTIONS" in result.warnings


async def test_empty_or_interim_input_never_calls_model() -> None:
    class MustNotRun:
        async def summarize(self, transcript):
            pytest.fail("No finalized candidate speech should skip the model")

    interim = utterance("u", "CANDIDATE", "진행 중", 0, pass_type="INTERIM")
    agent = ContextAnalysisAgent(MustNotRun())
    for utterances in [[], [interim]]:
        result = await agent.analyze(
            TranscriptSnapshot(session_id="s", utterances=utterances)
        )
        assert result.status == "empty"
        assert result.summary_result is None


async def test_unanswered_question_survives_without_llm() -> None:
    result = await ContextAnalysisAgent(ExtractiveSummarizer()).analyze(
        TranscriptSnapshot(
            session_id="s",
            utterances=[utterance("q", "INTERVIEWER", "경험은요?", 0)],
        )
    )
    assert result.status == "empty"
    assert result.qa_pairs[0].question_text == "경험은요?"
    assert "UNANSWERED_QUESTIONS" in result.warnings


async def test_provider_failure_preserves_qa_and_recovers_next_session(
    sample_transcript: TranscriptSnapshot,
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
    next_utterances = [
        u.model_copy(update={"session_id": "next"})
        for u in sample_transcript.utterances
    ]
    recovered = await agent.analyze(
        TranscriptSnapshot(
            session_id="next",
            stage=TranscriptStage.REALIGNED,
            utterances=next_utterances,
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
    sample_transcript: TranscriptSnapshot,
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
    sample_transcript: TranscriptSnapshot,
) -> None:
    result = await ContextAnalysisAgent(FakeSummarizer("상수 요약")).analyze(
        sample_transcript
    )
    assert result.status == "failed"
    assert result.error.code == "NO_GROUNDED_SUMMARY"


async def test_concurrent_sessions_stay_separate(
    sample_transcript: TranscriptSnapshot,
) -> None:
    other = TranscriptSnapshot(
        session_id="s",
        utterances=[utterance("a", "CANDIDATE", "디자인 시스템을 만들었습니다.", 0)],
    )
    agent = ContextAnalysisAgent(ExtractiveSummarizer())
    first, second = await asyncio.gather(
        agent.analyze(sample_transcript), agent.analyze(other)
    )
    assert first.summary_result.summary != second.summary_result.summary
    assert second.summary_result.source_utterance_ids == ["a"]
    assert second.unpaired_utterance_ids == ["a"]
    assert "FastAPI" not in second.summary_result.summary
