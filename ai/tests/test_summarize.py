from irya_ai.summarize import FakeSummarizer, Summarizer
from irya_ai.transcript import Transcript


def test_fake_summarizer_satisfies_protocol() -> None:
    assert isinstance(FakeSummarizer(summary=""), Summarizer)


async def test_fake_summarizer_returns_preset_summary(
    sample_transcript: Transcript,
) -> None:
    summarizer = FakeSummarizer(
        summary="3년차 백엔드 지원자, FastAPI 전환 경험.",
        key_points=["FastAPI 전환"],
    )

    result = await summarizer.summarize(sample_transcript)

    assert result.session_id == sample_transcript.session_id
    assert result.summary == "3년차 백엔드 지원자, FastAPI 전환 경험."
    assert result.key_points == ["FastAPI 전환"]
    assert result.model == "fake"


async def test_summary_sources_reference_final_utterances_only(
    sample_transcript: Transcript,
) -> None:
    result = await FakeSummarizer(summary="요약").summarize(sample_transcript)

    assert result.source_utterance_ids == ["u-001", "u-002", "u-003", "u-004"]
