import time

import pytest
from pydantic import ValidationError

from irya_ai.schemas import PassType, SpeakerRole
from irya_ai.simulator import TranscriptScript, TranscriptSimulator


@pytest.fixture
def script() -> TranscriptScript:
    return TranscriptScript.model_validate(
        {
            "sessionId": "ses_test",
            "title": "test",
            "turns": [
                {
                    "speaker": "INTERVIEWER",
                    "startMs": 0,
                    "endMs": 3000,
                    "content": "자기소개 부탁드립니다.",
                },
                {
                    "speaker": "CANDIDATE",
                    "startMs": 3500,
                    "endMs": 9500,
                    "content": "안녕하세요 정민호입니다 백엔드를 개발했습니다",
                },
                {
                    "speaker": "INTERVIEWER",
                    "startMs": 9000,
                    "endMs": 11000,
                    "content": "네",
                },
            ],
        }
    )


def test_script_rejects_unordered_turns() -> None:
    with pytest.raises(ValidationError, match="ordered by start_ms"):
        TranscriptScript.model_validate(
            {
                "sessionId": "ses_test",
                "title": "bad",
                "turns": [
                    {
                        "speaker": "INTERVIEWER",
                        "startMs": 5000,
                        "endMs": 6000,
                        "content": "b",
                    },
                    {
                        "speaker": "CANDIDATE",
                        "startMs": 1000,
                        "endMs": 2000,
                        "content": "a",
                    },
                ],
            }
        )


def test_finals_match_turns_in_order(script: TranscriptScript) -> None:
    finals = TranscriptSimulator(script).finals()

    assert [u.seq for u in finals] == [0, 1, 2]
    assert [u.content for u in finals] == [t.content for t in script.turns]
    assert [u.speaker for u in finals] == [t.speaker for t in script.turns]
    assert all(u.is_final for u in finals)
    assert len({u.utterance_id for u in finals}) == 3


def test_interim_events_precede_final_and_grow(script: TranscriptScript) -> None:
    events = list(TranscriptSimulator(script, interim_chunks=2).events())
    for_turn_1 = [u for u in events if u.seq == 1]

    assert [u.pass_type for u in for_turn_1] == [
        PassType.INTERIM,
        PassType.INTERIM,
        PassType.FINAL,
    ]
    contents = [u.content for u in for_turn_1]
    assert contents[0] != contents[1]
    assert contents[2].startswith(contents[1])
    assert contents[1].startswith(contents[0])
    assert for_turn_1[0].end_ms < for_turn_1[1].end_ms < for_turn_1[2].end_ms
    assert all(u.utterance_id == "utt_001" for u in for_turn_1)


def test_single_word_turn_emits_no_interim(script: TranscriptScript) -> None:
    events = list(TranscriptSimulator(script, interim_chunks=3).events())
    for_turn_2 = [u for u in events if u.seq == 2]

    assert len(for_turn_2) == 1
    assert for_turn_2[0].is_final


def test_events_are_ordered_by_arrival_time(script: TranscriptScript) -> None:
    timed = TranscriptSimulator(script, interim_chunks=2).timed_events()

    emit_times = [e.emit_ms for e in timed]
    assert emit_times == sorted(emit_times)
    # turn 2 starts at 9000 while turn 1 ends at 9500: turn 1's last interim
    # must arrive before turn 2's final, and turn 1's final after it.
    seq_by_time = [(e.emit_ms, e.utterance.seq, e.utterance.pass_type) for e in timed]
    assert (9500, 1, PassType.FINAL) in seq_by_time
    assert seq_by_time.index((11000, 2, PassType.FINAL)) > seq_by_time.index(
        (9500, 1, PassType.FINAL)
    )


def test_tracks_cover_both_roles(script: TranscriptScript) -> None:
    tracks = TranscriptSimulator(script).tracks()

    assert {t.role for t in tracks} == {SpeakerRole.INTERVIEWER, SpeakerRole.CANDIDATE}
    assert {t.track_id for t in tracks} == {"trk_interviewer", "trk_candidate"}
    assert all(t.session_id == "ses_test" for t in tracks)


def test_interim_chunks_must_be_non_negative(script: TranscriptScript) -> None:
    with pytest.raises(ValueError):
        TranscriptSimulator(script, interim_chunks=-1)


async def test_stream_without_realtime_yields_everything(
    script: TranscriptScript,
) -> None:
    simulator = TranscriptSimulator(script, interim_chunks=1)

    streamed = [u async for u in simulator.stream()]

    assert streamed == list(simulator.events())


async def test_stream_realtime_respects_speed(script: TranscriptScript) -> None:
    simulator = TranscriptSimulator(script, interim_chunks=0)

    started = time.perf_counter()
    streamed = [u async for u in simulator.stream(realtime=True, speed=1000)]
    elapsed = time.perf_counter() - started

    assert len(streamed) == 3
    # 11s of script at 1000x is 11ms; allow generous slack for CI.
    assert elapsed < 2.0


async def test_stream_rejects_non_positive_speed(script: TranscriptScript) -> None:
    with pytest.raises(ValueError):
        async for _ in TranscriptSimulator(script).stream(speed=0):
            pass


def test_split_sentences_yields_one_utterance_per_sentence() -> None:
    script = TranscriptScript.model_validate(
        {
            "sessionId": "ses_split",
            "title": "split",
            "turns": [
                {
                    "speaker": "CANDIDATE",
                    "startMs": 0,
                    "endMs": 9000,
                    "content": "첫 문장입니다. 두 번째 문장인가요? 셋째!",
                }
            ],
        }
    )

    finals = TranscriptSimulator(script, split_sentences=True).finals()

    assert [u.content for u in finals] == [
        "첫 문장입니다.",
        "두 번째 문장인가요?",
        "셋째!",
    ]
    assert [u.seq for u in finals] == [0, 1, 2]
    assert finals[0].start_ms == 0 and finals[-1].end_ms == 9000
    for prev, curr in zip(finals, finals[1:], strict=False):
        assert prev.end_ms == curr.start_ms
    assert " ".join(u.content for u in finals) == script.turns[0].content


def test_latency_shifts_arrival_but_not_speech_times(script: TranscriptScript) -> None:
    plain = TranscriptSimulator(script, interim_chunks=1).timed_events()
    delayed = TranscriptSimulator(
        script, interim_chunks=1, latency_ms=800
    ).timed_events()

    assert [e.emit_ms for e in delayed] == [e.emit_ms + 800 for e in plain]
    assert [e.utterance for e in delayed] == [e.utterance for e in plain]
    with pytest.raises(ValueError):
        TranscriptSimulator(script, latency_ms=-1)


def test_synthesized_words_cover_the_utterance(script: TranscriptScript) -> None:
    finals = TranscriptSimulator(script, synthesize_words=True).finals()
    answer = finals[1]

    assert [w.content for w in answer.words] == answer.content.split()
    assert answer.words[0].start_ms == answer.start_ms
    assert answer.words[-1].end_ms == answer.end_ms
    for prev, curr in zip(answer.words, answer.words[1:], strict=False):
        assert prev.end_ms == curr.start_ms
    assert all(w.end_ms >= w.start_ms for w in answer.words)
    assert TranscriptSimulator(script).finals()[1].words == []
