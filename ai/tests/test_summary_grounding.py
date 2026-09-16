import unicodedata

import pytest

from irya_ai.schemas import TranscriptSnapshot
from irya_ai.summarize import CitationDraft, PointDraft, SummaryDraft, ground_summary


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
        point("경험이 있다", "u-003", "전환하면서 어떤 성과가 있었나요?"),
        point("성과가 있다", "u-004", "응답 시간을 70% 줄였다"),
        point("성과가 있다", "u-004", " "),
        point("배포가 주 3회다", "u-004", "응답 시간을 40% 줄였고"),
        PointDraft(text="무근거 요약", citations=[]),
        point(" ", "u-004", "응답 시간을 40% 줄였고"),
        # quote 의 영문 대소문자를 바꾼 경우 (원문: "Django에서 FastAPI로")
        point("프레임워크를 전환했다고 설명했다.", "u-002", "django에서 FastAPI로"),
        # 단어 사이 공백을 지운 경우
        point(
            "프레임워크를 전환했다고 설명했다.", "u-002", "Django에서 FastAPI로전환하는"
        ),
        # 단어 사이에 공백을 넣은 경우
        point(
            "프레임워크를 전환했다고 설명했다.",
            "u-002",
            "Django에서 FastAPI 로 전환하는",
        ),
    ],
)
def test_invalid_claim_is_removed_from_all_display_fields(
    sample_transcript: TranscriptSnapshot, bad_point: PointDraft
) -> None:
    result = ground_summary(
        sample_transcript, SummaryDraft(points=[GOOD_POINT, bad_point]), model="test"
    )
    assert result.key_points == [GOOD_POINT.text]
    assert result.summary == GOOD_POINT.text
    assert result.source_utterance_ids == ["u-004"]
    assert result.rejected_point_count == 1


def test_one_bad_citation_rejects_whole_claim(
    sample_transcript: TranscriptSnapshot,
) -> None:
    mixed = GOOD_POINT.model_copy(deep=True)
    mixed.citations.append(CitationDraft(utterance_id="missing", quote="없음"))
    result = ground_summary(
        sample_transcript, SummaryDraft(points=[mixed]), model="test"
    )
    assert result.points == []
    assert result.summary == ""


def test_times_and_speaker_come_from_transcript(
    sample_transcript: TranscriptSnapshot,
) -> None:
    result = ground_summary(
        sample_transcript, SummaryDraft(points=[GOOD_POINT]), model="test"
    )
    evidence = result.points[0].evidence[0]
    assert (evidence.start_ms, evidence.end_ms) == (15500, 24000)
    assert evidence.speaker == "CANDIDATE"


def test_grounding_reuses_whitespace_normalized_quote_lookup(
    sample_transcript: TranscriptSnapshot,
) -> None:
    spaced = point("응답 시간을 40% 줄였다.", "u-004", "응답 시간을   40% 줄였고")
    result = ground_summary(
        sample_transcript, SummaryDraft(points=[spaced]), model="test"
    )
    assert result.points[0].text == spaced.text


def test_summary_text_may_lowercase_english_when_quote_is_verbatim(
    sample_transcript: TranscriptSnapshot,
) -> None:
    """``text`` may be rewritten; only ``quote`` must match the source exactly."""
    lowered = point(
        "django에서 fastapi로 전환한 경험을 설명했다.",
        "u-002",
        "Django에서 FastAPI로 전환하는 작업을 맡았습니다.",
    )
    result = ground_summary(
        sample_transcript, SummaryDraft(points=[lowered]), model="test"
    )
    assert result.key_points == [lowered.text]
    assert result.rejected_point_count == 0


def test_decomposed_quote_is_grounded_after_nfc(
    sample_transcript: TranscriptSnapshot,
) -> None:
    exact = "응답 시간을 40% 줄였고"
    decomposed = unicodedata.normalize("NFD", exact)
    assert decomposed != exact  # guard: NFD really differs before NFC

    result = ground_summary(
        sample_transcript,
        SummaryDraft(points=[point(GOOD_POINT.text, "u-004", decomposed)]),
        model="test",
    )
    assert result.key_points == [GOOD_POINT.text]
    assert result.rejected_point_count == 0
