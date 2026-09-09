from irya_ai.evaluation import missing_key_facts, unsupported_numbers
from irya_ai.transcript import Transcript

KEY_FACTS = ["3년차", "Django", "FastAPI", "40%"]

GOOD_SUMMARY = (
    "3년차 백엔드 지원자. 정산 서비스를 Django에서 FastAPI로 전환해 "
    "평균 응답 시간을 40% 줄였다."
)

BAD_SUMMARY = "5년차 지원자. 응답 시간을 70% 줄였고 Kubernetes를 도입했다."


def test_good_summary_keeps_all_key_facts() -> None:
    assert missing_key_facts(GOOD_SUMMARY, KEY_FACTS) == []


def test_missing_key_facts_are_reported() -> None:
    assert missing_key_facts(BAD_SUMMARY, KEY_FACTS) == [
        "3년차",
        "Django",
        "FastAPI",
        "40%",
    ]


def test_key_fact_matching_ignores_whitespace_and_case() -> None:
    assert missing_key_facts("fastapi 로 전환했다", ["FastAPI"]) == []


def test_good_summary_adds_no_numbers(sample_transcript: Transcript) -> None:
    assert unsupported_numbers(sample_transcript, GOOD_SUMMARY) == []


def test_numbers_absent_from_transcript_are_flagged(
    sample_transcript: Transcript,
) -> None:
    assert unsupported_numbers(sample_transcript, BAD_SUMMARY) == ["5", "70"]


def test_repeated_unsupported_numbers_are_reported_once(
    sample_transcript: Transcript,
) -> None:
    assert unsupported_numbers(sample_transcript, "70%에서 70%로") == ["70"]
