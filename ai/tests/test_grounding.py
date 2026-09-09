import pytest

from irya_ai.summarize import CitationDraft, PointDraft, SummaryDraft, ground_summary
from irya_ai.transcript import Transcript


def point(text: str, uid: str, quote: str) -> PointDraft:
    return PointDraft(
        text=text, citations=[CitationDraft(utterance_id=uid, quote=quote)]
    )


GOOD_POINT = point(
    "응답 시간을 40% 줄였다고 설명했다.", "u-004", "응답 시간을 40% 줄였고"
)


@pytest.mark.parametrize(
    "bad_point",
    [
        point("성과가 있다", "unknown", "성과"),
        point("중간 전사", "u-004-partial", "평균 응답 시간을"),
        point("경험이 있다", "u-003", "전환하면서 어떤 성과가 있었나요?"),
        point("성과가 있다", "u-004", "응답 시간을 70% 줄였다"),
        point("성과가 있다", "u-004", " "),
        point("배포가 주 3회다", "u-004", "응답 시간을 40% 줄였고"),
        PointDraft(text="무근거 요약", citations=[]),
        point(" ", "u-004", "응답 시간을 40% 줄였고"),
    ],
)
def test_invalid_claim_is_removed_from_all_display_fields(
    sample_transcript: Transcript, bad_point: PointDraft
) -> None:
    result = ground_summary(
        sample_transcript, SummaryDraft(points=[GOOD_POINT, bad_point]), model="test"
    )
    assert result.key_points == [GOOD_POINT.text]
    assert result.summary == GOOD_POINT.text
    assert result.source_utterance_ids == ["u-004"]
    assert result.rejected_point_count == 1


def test_one_bad_citation_rejects_whole_claim(sample_transcript: Transcript) -> None:
    mixed = GOOD_POINT.model_copy(deep=True)
    mixed.citations.append(CitationDraft(utterance_id="missing", quote="없음"))
    result = ground_summary(
        sample_transcript, SummaryDraft(points=[mixed]), model="test"
    )
    assert result.points == []
    assert result.summary == ""


def test_times_and_speaker_come_from_transcript(sample_transcript: Transcript) -> None:
    result = ground_summary(
        sample_transcript, SummaryDraft(points=[GOOD_POINT]), model="test"
    )
    evidence = result.points[0].evidence[0]
    assert (evidence.started_at_ms, evidence.ended_at_ms) == (15500, 24000)
    assert evidence.speaker == "candidate"
