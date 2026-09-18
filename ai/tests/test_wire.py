"""The ``/internal/v1`` payloads, checked against the agreed JSON key by key.

These are contract tests, not schema tests: the assertions name the literal
camelCase keys from the Backend agreement, so renaming a field here fails the
suite instead of failing a request at the interview.
"""

import pytest
from pydantic import ValidationError

from irya_ai.schemas.transcript import SpeakerRole, Utterance
from irya_ai.schemas.wire import TranscriptPayload, transcript_payload


def utterance(**overrides) -> Utterance:
    fields = {
        "utterance_id": "utt_001",
        "session_id": "ses_123",
        "track_id": "trk_candidate",
        "speaker": SpeakerRole.CANDIDATE,
        "seq": 0,
        "start_ms": 15_200,
        "end_ms": 23_800,
        "content": "인턴 당시 React Native로 지도 기능을 개발했습니다.",
    }
    return Utterance(**{**fields, **overrides})


def test_the_payload_serialises_to_the_agreed_keys() -> None:
    payload = transcript_payload(utterance(), participant_id="candidate_123")

    assert payload.model_dump(by_alias=True) == {
        "utteranceId": "utt_001",
        "participantId": "candidate_123",
        "speaker": "CANDIDATE",
        "text": "인턴 당시 React Native로 지도 기능을 개발했습니다.",
        "startedAtMs": 15_200,
        "endedAtMs": 23_800,
    }


def test_the_payload_carries_nothing_the_contract_did_not_ask_for() -> None:
    """``sessionId`` is in the path, and the pipeline's own fields stay home."""

    keys = set(transcript_payload(utterance(), participant_id="p_1").model_dump())

    assert keys.isdisjoint(
        {"session_id", "track_id", "seq", "pass_type", "uncertain", "words"}
    )


def test_the_utterance_keeps_its_own_field_names() -> None:
    """The translation is one-way: nothing here renames the TechSpec model."""

    source = utterance()

    transcript_payload(source, participant_id="candidate_123")

    assert source.content == "인턴 당시 React Native로 지도 기능을 개발했습니다."
    assert (source.start_ms, source.end_ms) == (15_200, 23_800)
    assert source.track_id == "trk_candidate"


def test_a_participant_id_must_be_supplied() -> None:
    """The Agent has no participant id of its own; it cannot be defaulted."""

    with pytest.raises(TypeError):
        transcript_payload(utterance())  # type: ignore[call-arg]


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_participant_id_is_refused(blank: str) -> None:
    """A trackless placeholder would label every utterance with nothing."""

    with pytest.raises(ValidationError):
        transcript_payload(utterance(), participant_id=blank)


def test_an_unknown_key_is_refused_rather_than_dropped() -> None:
    """``extra="forbid"`` is what makes a contract drift visible."""

    with pytest.raises(ValidationError):
        TranscriptPayload(
            utteranceId="utt_001",
            participantId="candidate_123",
            speaker="CANDIDATE",
            text="네",
            startedAtMs=0,
            endedAtMs=1,
            trackId="trk_candidate",
        )


def test_a_backwards_span_is_refused() -> None:
    with pytest.raises(ValidationError):
        TranscriptPayload(
            utteranceId="utt_001",
            participantId="candidate_123",
            speaker="CANDIDATE",
            text="네",
            startedAtMs=3_000,
            endedAtMs=1_000,
        )


def test_the_payload_reads_the_agreed_keys_back() -> None:
    """Round-trip, because Backend may echo one of these at us."""

    payload = TranscriptPayload.model_validate(
        {
            "utteranceId": "utt_002",
            "participantId": "interviewer_7",
            "speaker": "INTERVIEWER",
            "text": "인턴 경험을 설명해주세요.",
            "startedAtMs": 0,
            "endedAtMs": 2_400,
        }
    )

    assert payload.speaker is SpeakerRole.INTERVIEWER
    assert payload.text == "인턴 경험을 설명해주세요."
