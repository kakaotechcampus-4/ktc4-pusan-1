"""The ``/internal/v1`` payloads, checked against the agreed JSON key by key.

These are contract tests, not schema tests: the assertions name the literal
camelCase keys from the Backend agreement, so renaming a field here fails the
suite instead of failing a request at the interview.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from irya_ai.schemas.analysis import SuggestedQuestion
from irya_ai.schemas.transcript import SpeakerRole, Utterance
from irya_ai.schemas.wire import (
    SuggestionPayload,
    SuggestionType,
    TranscriptPayload,
    suggestion_payload,
    transcript_payload,
)


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


def test_an_interim_utterance_cannot_overwrite_a_final_on_the_wire() -> None:
    with pytest.raises(ValueError, match="only FINAL"):
        transcript_payload(
            utterance(pass_type="INTERIM"), participant_id="candidate_123"
        )


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


# --- suggestions ------------------------------------------------------------


def question(**overrides) -> SuggestedQuestion:
    fields = {
        "question_id": "sug_001",
        "session_id": "ses_123",
        "qa_id": "qa_003",
        "content": "말씀하신 캐시 무효화 전략을 어떻게 검증했는지 질문해보세요.",
        "reason": "지원자가 캐시를 언급했습니다.",
        "evidence_utterance_ids": ["utt_001", "utt_002"],
        "generated_at": datetime(2026, 9, 18, 9, 0, tzinfo=UTC),
    }
    return SuggestedQuestion(**{**fields, **overrides})


def test_the_suggestion_payload_serialises_to_the_agreed_keys() -> None:
    payload = suggestion_payload(question())

    assert payload.model_dump(by_alias=True) == {
        "suggestionId": "sug_001",
        "type": "FOLLOW_UP",
        "content": "말씀하신 캐시 무효화 전략을 어떻게 검증했는지 질문해보세요.",
        "evidenceUtteranceIds": ["utt_001", "utt_002"],
    }


def test_the_suggestion_payload_leaves_the_pipeline_s_own_fields_at_home() -> None:
    """``reason`` is for the interviewer; ``status`` is Backend's to keep."""

    keys = set(suggestion_payload(question()).model_dump())

    assert keys.isdisjoint({"reason", "status", "qa_id", "session_id", "asked_at"})


def test_a_suggestion_without_evidence_cannot_be_put_on_the_wire() -> None:
    """The grounding gate runs first, but the contract refuses it too."""

    with pytest.raises(ValidationError):
        suggestion_payload(question(evidence_utterance_ids=[]))


def test_the_suggestion_payload_refuses_a_key_the_contract_never_agreed() -> None:
    with pytest.raises(ValidationError):
        SuggestionPayload(
            suggestionId="sug_001",
            type="FOLLOW_UP",
            content="더 여쭤보세요.",
            evidenceUtteranceIds=["utt_001"],
            qaId="qa_003",
        )


def test_the_only_type_the_meeting_showed_is_the_default() -> None:
    assert [t.value for t in SuggestionType] == ["FOLLOW_UP"]
    assert suggestion_payload(question()).type is SuggestionType.FOLLOW_UP
