import pytest
from pydantic import ValidationError

from irya_ai.transcript import Speaker, Transcript, Utterance


def test_sample_transcript_loads(sample_transcript: Transcript) -> None:
    assert sample_transcript.session_id == "sample-session-001"
    assert len(sample_transcript.utterances) == 5


def test_final_utterances_exclude_provisional_results(
    sample_transcript: Transcript,
) -> None:
    finals = sample_transcript.final_utterances()

    assert [u.utterance_id for u in finals] == ["u-001", "u-002", "u-003", "u-004"]


def test_final_utterances_are_sorted_by_start_time() -> None:
    transcript = Transcript(
        session_id="s",
        utterances=[
            Utterance(
                utterance_id="late",
                speaker=Speaker.CANDIDATE,
                text="나중 발화",
                started_at_ms=5000,
                ended_at_ms=6000,
            ),
            Utterance(
                utterance_id="early",
                speaker=Speaker.INTERVIEWER,
                text="먼저 발화",
                started_at_ms=0,
                ended_at_ms=1000,
            ),
        ],
    )

    assert [u.utterance_id for u in transcript.final_utterances()] == [
        "early",
        "late",
    ]


def test_full_text_labels_speakers(sample_transcript: Transcript) -> None:
    text = sample_transcript.full_text()
    lines = text.splitlines()

    assert len(lines) == 4
    assert lines[0] == "interviewer: 간단히 자기소개 부탁드립니다."
    assert lines[1].startswith("candidate: 3년차 백엔드 개발자")


def test_utterance_rejects_reversed_time_range() -> None:
    with pytest.raises(ValidationError):
        Utterance(
            utterance_id="u-bad",
            speaker=Speaker.CANDIDATE,
            text="시간 역전",
            started_at_ms=2000,
            ended_at_ms=1000,
        )


def test_utterance_rejects_negative_start() -> None:
    with pytest.raises(ValidationError):
        Utterance(
            utterance_id="u-bad",
            speaker=Speaker.CANDIDATE,
            text="음수 시각",
            started_at_ms=-1,
            ended_at_ms=1000,
        )


def test_latest_final_revision_wins_even_when_interim_arrives_last(
    sample_transcript: Transcript,
) -> None:
    source = sample_transcript.utterances[-1]
    revisions = [
        source.model_copy(update={"text": "40% 감소했습니다."}),
        source.model_copy(update={"text": "45% 감소했습니다."}),
        source.model_copy(update={"text": "45%", "is_final": False}),
    ]
    transcript = Transcript(session_id="s", utterances=revisions)
    assert len(transcript.final_utterances()) == 1
    assert transcript.final_utterances()[0].text == "45% 감소했습니다."


def test_conflicting_identity_in_revisions_is_rejected(
    sample_transcript: Transcript,
) -> None:
    source = sample_transcript.utterances[-1]
    with pytest.raises(ValidationError):
        Transcript(
            session_id="s",
            utterances=[source, source.model_copy(update={"speaker": "interviewer"})],
        )


@pytest.mark.parametrize("text", ["", " \n "])
def test_blank_final_text_is_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        Utterance(
            utterance_id="u",
            speaker="candidate",
            text=text,
            started_at_ms=0,
            ended_at_ms=1,
        )
