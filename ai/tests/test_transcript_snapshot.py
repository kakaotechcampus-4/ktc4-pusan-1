import pytest
from pydantic import ValidationError

from irya_ai.schemas import (
    PassType,
    SpeakerRole,
    TranscriptSnapshot,
    TranscriptStage,
    Utterance,
)


def utterance(
    uid: str,
    speaker: SpeakerRole,
    content: str,
    seq: int,
    **overrides,
) -> Utterance:
    base = {
        "utterance_id": uid,
        "session_id": "s",
        "track_id": f"trk_{speaker.value.lower()}",
        "speaker": speaker,
        "seq": seq,
        "content": content,
        "start_ms": seq * 1000,
        "end_ms": seq * 1000 + 900,
    }
    return Utterance(**{**base, **overrides})


def test_sample_snapshot_loads(sample_transcript: TranscriptSnapshot) -> None:
    assert sample_transcript.session_id == "sample-session-001"
    assert sample_transcript.stage is TranscriptStage.LIVE
    assert len(sample_transcript.utterances) == 5


def test_final_utterances_exclude_provisional_results(
    sample_transcript: TranscriptSnapshot,
) -> None:
    finals = sample_transcript.final_utterances()
    assert [u.utterance_id for u in finals] == ["u-001", "u-002", "u-003", "u-004"]


def test_final_utterances_are_sorted_by_seq() -> None:
    snapshot = TranscriptSnapshot(
        session_id="s",
        utterances=[
            utterance("late", SpeakerRole.CANDIDATE, "나중 발화", 5),
            utterance("early", SpeakerRole.INTERVIEWER, "먼저 발화", 0),
        ],
    )
    assert [u.utterance_id for u in snapshot.final_utterances()] == ["early", "late"]


def test_latest_final_revision_wins_even_when_interim_arrives_last() -> None:
    source = utterance("u", SpeakerRole.CANDIDATE, "40% 감소했습니다.", 0)
    revisions = [
        source,
        source.model_copy(update={"content": "45% 감소했습니다."}),
        source.model_copy(update={"content": "45%", "pass_type": PassType.INTERIM}),
    ]
    snapshot = TranscriptSnapshot(session_id="s", utterances=revisions)
    assert len(snapshot.final_utterances()) == 1
    assert snapshot.final_utterances()[0].content == "45% 감소했습니다."


@pytest.mark.parametrize(
    "changed",
    [
        {"track_id": "trk_other"},
        {"speaker": SpeakerRole.INTERVIEWER},
        {"seq": 1},
        {"start_ms": 1},
    ],
)
def test_conflicting_identity_in_revisions_is_rejected(changed: dict) -> None:
    source = utterance("u", SpeakerRole.CANDIDATE, "답변", 0)
    with pytest.raises(ValidationError, match="must keep"):
        TranscriptSnapshot(
            session_id="s",
            utterances=[source, source.model_copy(update=changed)],
        )


def test_utterance_session_must_match_snapshot() -> None:
    source = utterance("u", SpeakerRole.CANDIDATE, "답변", 0)
    with pytest.raises(ValidationError, match="must match"):
        TranscriptSnapshot(
            session_id="other",
            utterances=[source],
        )


def test_utterance_rejects_negative_start() -> None:
    with pytest.raises(ValidationError):
        utterance(
            "u",
            SpeakerRole.CANDIDATE,
            "답변",
            0,
            start_ms=-1,
        )


@pytest.mark.parametrize("content", ["", " \n "])
def test_blank_final_content_is_rejected(content: str) -> None:
    with pytest.raises(ValidationError):
        utterance("u", SpeakerRole.CANDIDATE, content, 0)


def test_full_text_labels_speakers(sample_transcript: TranscriptSnapshot) -> None:
    lines = sample_transcript.full_text().splitlines()
    assert len(lines) == 4
    assert lines[0] == "INTERVIEWER: 간단히 자기소개 부탁드립니다."
    assert lines[1].startswith("CANDIDATE: 3년차 백엔드 개발자")
