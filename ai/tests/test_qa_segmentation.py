import json
from pathlib import Path

import pytest

from irya_ai.pipeline import QASegmenter, is_question, segment_qa
from irya_ai.pipeline.qa_segmentation import ANSWER_ROLE, QUESTION_ROLE, is_backchannel
from irya_ai.schemas import PassType, SpeakerRole, Utterance
from irya_ai.simulator import TranscriptSimulator, load_script

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
GOLDEN = Path(__file__).resolve().parents[1] / "data" / "golden"


def _utt(seq: int, speaker: SpeakerRole, content: str, **overrides) -> Utterance:
    base = {
        "utterance_id": f"utt_{seq:03d}",
        "session_id": "ses_t",
        "track_id": f"trk_{speaker.value.lower()}",
        "speaker": speaker,
        "seq": seq,
        "start_ms": seq * 1000,
        "end_ms": seq * 1000 + 900,
        "content": content,
    }
    return Utterance(**{**base, **overrides})


INT, CAN = SpeakerRole.INTERVIEWER, SpeakerRole.CANDIDATE


@pytest.mark.parametrize(
    "text,expected",
    [
        ("캐시는 어디에 적용하셨나요?", True),
        ("자기소개 부탁드릴게요.", True),
        ("어떻게 정리했는지 궁금합니다.", True),
        ("네, 감사합니다. 오늘 면접은 여기까지 하겠습니다.", False),
        ("그렇군요.", False),
    ],
)
def test_is_question(text: str, expected: bool) -> None:
    assert is_question(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("네.", True),
        ("음, 그렇군요.", True),
        ("네, 알겠습니다.", True),
        ("왜요?", False),
    ],
)
def test_is_backchannel(text: str, expected: bool) -> None:
    assert is_backchannel(text) is expected


def test_basic_pairing_and_annotation() -> None:
    utts = [
        _utt(0, INT, "자기소개 부탁드릴게요."),
        _utt(1, CAN, "안녕하세요 정민호입니다."),
        _utt(2, INT, "캐시는 어디에 적용하셨나요?"),
        _utt(3, CAN, "상품 API 앞에 뒀습니다."),
    ]

    result = segment_qa(utts)

    assert [p.qa_id for p in result.qa_pairs] == ["qa_utt_000", "qa_utt_002"]
    first = result.qa_pairs[0]
    assert first.question_utterance_ids == ["utt_000"]
    assert first.answer_utterance_ids == ["utt_001"]
    assert first.start_ms == 0 and first.end_ms == 1900
    assert first.answer_word_count == 2
    roles = {u.utterance_id: (u.qa_id, u.qa_role) for u in result.utterances}
    assert roles["utt_000"] == ("qa_utt_000", QUESTION_ROLE)
    assert roles["utt_001"] == ("qa_utt_000", ANSWER_ROLE)
    assert roles["utt_003"] == ("qa_utt_002", ANSWER_ROLE)
    assert not result.dropped


def test_qa_id_stays_stable_when_an_earlier_pair_is_inserted() -> None:
    existing = [
        _utt(10, INT, "캐시는 어디에 적용하셨나요?"),
        _utt(11, CAN, "상품 API 앞에 뒀습니다."),
    ]
    inserted = [
        _utt(0, INT, "자기소개 부탁드릴게요."),
        _utt(1, CAN, "안녕하세요."),
        *existing,
    ]

    before = segment_qa(existing).qa_pairs[0]
    after = segment_qa(inserted).qa_pairs[1]

    assert before.qa_id == after.qa_id == "qa_utt_010"


def test_consecutive_candidate_utterances_form_one_answer() -> None:
    utts = [
        _utt(0, INT, "가장 어려웠던 문제가 뭐였나요?"),
        _utt(1, CAN, "주문 API가 느려지는 문제였습니다."),
        _utt(2, CAN, "슬로우 쿼리 로그를 켜고 봤더니"),
        _utt(3, CAN, "인덱스를 안 타는 쿼리가 있었습니다."),
    ]

    result = segment_qa(utts)

    assert len(result.qa_pairs) == 1
    pair = result.qa_pairs[0]
    assert pair.answer_utterance_ids == ["utt_001", "utt_002", "utt_003"]
    assert pair.answer_text.startswith("주문 API가") and pair.answer_text.endswith(
        "있었습니다."
    )
    assert pair.end_ms == 3900


def test_backchannel_does_not_split_an_answer() -> None:
    utts = [
        _utt(0, INT, "갈등이 있었던 적이 있나요?"),
        _utt(1, CAN, "코드 리뷰를 세게 하는 팀원이 있었는데"),
        _utt(2, INT, "네."),
        _utt(3, CAN, "나중에는 리뷰 기준을 같이 정리했습니다."),
    ]

    result = segment_qa(utts)

    assert len(result.qa_pairs) == 1
    assert result.qa_pairs[0].answer_utterance_ids == ["utt_001", "utt_003"]
    assert [(u.utterance_id, r) for u, r in result.dropped] == [
        ("utt_002", "backchannel")
    ]
    dropped_utt = next(u for u in result.utterances if u.utterance_id == "utt_002")
    assert dropped_utt.qa_id is None


def test_unanswered_question_is_kept_but_closing_remark_is_dropped() -> None:
    utts = [
        _utt(0, INT, "온콜 대응은 괜찮으세요?"),
        _utt(1, INT, "네, 감사합니다. 오늘 면접은 여기까지 하겠습니다."),
    ]
    # Both interviewer turns merge into one; it is a question, so kept unanswered.
    result = segment_qa(utts)
    assert len(result.qa_pairs) == 1
    assert result.qa_pairs[0].answer_utterance_ids == []

    utts = [
        _utt(0, INT, "온콜 대응은 괜찮으세요?"),
        _utt(1, CAN, "네, 괜찮습니다."),
        _utt(2, INT, "네, 감사합니다. 오늘 면접은 여기까지 하겠습니다."),
    ]
    result = segment_qa(utts)
    assert len(result.qa_pairs) == 1
    assert [r for _, r in result.dropped] == ["unanswered non-question"]


def test_candidate_speech_before_first_question_is_dropped() -> None:
    utts = [
        _utt(0, CAN, "안녕하세요, 잘 들리시나요?"),
        _utt(1, INT, "네, 자기소개 부탁드릴게요."),
        _utt(2, CAN, "정민호입니다."),
    ]

    result = segment_qa(utts)

    assert len(result.qa_pairs) == 1
    assert result.qa_pairs[0].question_utterance_ids == ["utt_001"]
    assert result.dropped[0][1] == "candidate speech before any question"


def test_interim_utterances_are_ignored() -> None:
    utts = [
        _utt(0, INT, "자기소개 부탁드릴게요."),
        _utt(1, CAN, "안녕", pass_type=PassType.INTERIM),
        _utt(1, CAN, "안녕하세요 정민호입니다."),
    ]

    result = segment_qa(utts)

    assert result.qa_pairs[0].answer_utterance_ids == ["utt_001"]
    assert len(result.utterances) == 2


def test_empty_input() -> None:
    result = segment_qa([])
    assert result.qa_pairs == [] and result.utterances == []


@pytest.mark.parametrize("split", [False, True], ids=["whole-turns", "split-sentences"])
@pytest.mark.parametrize(
    "golden_path", sorted(GOLDEN.glob("qa_*.json")), ids=lambda p: p.name
)
def test_samples_match_golden(golden_path: Path, split: bool) -> None:
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    script = load_script(SAMPLES / golden["source"])
    finals = TranscriptSimulator(
        script, interim_chunks=0, split_sentences=split
    ).finals()

    result = segment_qa(finals)

    assert len(result.qa_pairs) == len(golden["pairs"])
    for pair, expected in zip(result.qa_pairs, golden["pairs"], strict=True):
        assert pair.question_text == expected["question"]
        assert bool(pair.answer_text) is expected["hasAnswer"]
        assert pair.answer_text.startswith(expected["answerStartsWith"])
        if "answerEndsWith" in expected:
            assert pair.answer_text.endswith(expected["answerEndsWith"])
        assert pair.session_id == golden["sessionId"]
    if split:
        # Sentence splitting must not change the reassembled text.
        assert all(len(p.question_utterance_ids) >= 1 for p in result.qa_pairs)
        assert any(len(p.answer_utterance_ids) > 1 for p in result.qa_pairs)


def test_streaming_segmenter_emits_pairs_as_questions_close() -> None:
    script = load_script(SAMPLES / "transcript_backend_junior_02.json")
    finals = TranscriptSimulator(script, interim_chunks=1).finals()
    batch = segment_qa(finals).qa_pairs

    segmenter = QASegmenter()
    emitted = []
    open_ids_seen = []
    for u in TranscriptSimulator(script, interim_chunks=1).events():
        emitted.extend(segmenter.feed(u))
        current = segmenter.current()
        if current is not None:
            open_ids_seen.append(current.qa_id)
    emitted.extend(segmenter.flush())

    assert [p.qa_id for p in emitted] == [p.qa_id for p in batch]
    assert emitted == batch
    # The open pair advanced one id at a time and never went backwards.
    assert open_ids_seen == sorted(open_ids_seen)
    assert segmenter.flush() == []
