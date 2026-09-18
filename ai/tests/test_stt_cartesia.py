"""Provider events in, utterances out - including the events that must not be.

The seam under test is the conversion, so the events are built here rather
than fetched: ``SpeechEvent`` and ``SpeechData`` are plain dataclasses, and a
test that needed a WebSocket could not assert anything about a provider that
returns no timing without asking a paid endpoint to misbehave on cue.
"""

import pytest
from livekit.agents import stt as livekit_stt
from livekit.agents.types import NOT_GIVEN, TimedString

from irya_ai.config import Settings
from irya_ai.schemas.transcript import (
    PassType,
    SpeakerRole,
    TranscriptSnapshot,
    Utterance,
)
from irya_ai.stt.cartesia import (
    REASON_EMPTY,
    REASON_NO_TIMING,
    REASON_OUT_OF_ORDER,
    REASON_TIMESTAMP_INVALID,
    CartesiaTranscriptionStream,
    build_stt,
)
from irya_ai.stt.session import SessionOrdering


def final(
    text: str,
    start_s: float,
    end_s: float,
    *,
    words: list[TimedString] | None = None,
) -> livekit_stt.SpeechEvent:
    return speech_event(
        livekit_stt.SpeechEventType.FINAL_TRANSCRIPT, text, start_s, end_s, words
    )


def interim(text: str, start_s: float, end_s: float) -> livekit_stt.SpeechEvent:
    return speech_event(
        livekit_stt.SpeechEventType.INTERIM_TRANSCRIPT, text, start_s, end_s, None
    )


def speech_event(
    event_type: livekit_stt.SpeechEventType,
    text: str,
    start_s: float,
    end_s: float,
    words: list[TimedString] | None,
) -> livekit_stt.SpeechEvent:
    return livekit_stt.SpeechEvent(
        type=event_type,
        alternatives=[
            livekit_stt.SpeechData(
                language="ko",
                text=text,
                start_time=start_s,
                end_time=end_s,
                words=words,
            )
        ],
    )


async def feed(*events: livekit_stt.SpeechEvent):
    for event in events:
        yield event


def stream_for(**kwargs) -> CartesiaTranscriptionStream:
    kwargs.setdefault("session_id", "ses_test")
    kwargs.setdefault("track_id", "trk_candidate")
    kwargs.setdefault("speaker", SpeakerRole.CANDIDATE)
    return CartesiaTranscriptionStream(**kwargs)


async def collect(stream: CartesiaTranscriptionStream, *events) -> list[Utterance]:
    return [u async for u in stream.utterances(feed(*events))]


async def test_a_final_becomes_an_utterance() -> None:
    stream = stream_for()

    utterances = await collect(stream, final("레디스로 캐시를 붙였습니다", 1.2, 3.4))

    assert len(utterances) == 1
    utterance = utterances[0]
    assert utterance.content == "레디스로 캐시를 붙였습니다"
    assert utterance.utterance_id == "utt_trk_candidate_0000"
    assert utterance.session_id == "ses_test"
    assert utterance.speaker is SpeakerRole.CANDIDATE
    assert utterance.pass_type is PassType.FINAL
    assert utterance.start_ms == 1200
    assert utterance.end_ms == 3400
    assert utterance.words == []
    assert stream.rejected == []


async def test_ids_are_issued_in_order_and_zero_padded() -> None:
    """``final_utterances`` breaks a seq tie on this id, so it must sort."""

    stream = stream_for()

    utterances = await collect(
        stream, final("하나", 0.0, 1.0), final("둘", 1.0, 2.0), final("셋", 2.0, 3.0)
    )

    assert [u.utterance_id for u in utterances] == [
        "utt_trk_candidate_0000",
        "utt_trk_candidate_0001",
        "utt_trk_candidate_0002",
    ]
    assert [u.seq for u in utterances] == sorted(u.seq for u in utterances)
    assert len({u.seq for u in utterances}) == 3


async def test_an_empty_final_is_rejected_not_raised() -> None:
    """Cartesia does send these; ``content`` has ``min_length=1``."""

    stream = stream_for()

    assert await collect(stream, final("   ", 1.0, 2.0)) == []
    assert [r.reason for r in stream.rejected] == [REASON_EMPTY]
    assert stream.rejected[0].start_ms == 1000


async def test_a_provider_that_reports_no_timing_is_rejected() -> None:
    """``aligned_transcript=False`` means every span is 0.0 to 0.0 - ink-2 is.

    Accepting these would put the whole interview at time zero while every
    value still looked like a number.
    """

    stream = stream_for()

    assert await collect(stream, final("Ndapshigan Piguushibonin", 0.0, 0.0)) == []
    assert [r.reason for r in stream.rejected] == [REASON_NO_TIMING]


async def test_a_backwards_span_is_rejected() -> None:
    stream = stream_for()

    assert await collect(stream, final("뒤집힌 구간", 3.0, 1.0)) == []
    assert [r.reason for r in stream.rejected] == [REASON_TIMESTAMP_INVALID]


async def test_a_start_that_moves_backwards_is_rejected() -> None:
    """``seq`` is built from the start, so this would sort before what shipped."""

    stream = stream_for()

    utterances = await collect(
        stream,
        final("먼저", 2.0, 3.0),
        final("거꾸로", 1.0, 1.5),
        final("다음", 3.0, 4.0),
    )

    assert [u.content for u in utterances] == ["먼저", "다음"]
    assert [r.reason for r in stream.rejected] == [REASON_OUT_OF_ORDER]
    assert [u.seq for u in utterances] == sorted(u.seq for u in utterances)


async def test_equal_starts_keep_reading_order_through_the_id_tiebreak() -> None:
    """Two finals rounding to one millisecond share a seq; the id separates them."""

    stream = stream_for()

    utterances = await collect(stream, final("앞", 1.0, 1.4), final("뒤", 1.0004, 1.8))

    assert len({u.seq for u in utterances}) == 1
    snapshot = TranscriptSnapshot(session_id="ses_test", utterances=utterances)
    assert [u.content for u in snapshot.final_utterances()] == ["앞", "뒤"]


async def test_interim_events_are_counted_and_dropped() -> None:
    """Korean never produces these, and passing them through is an open design."""

    stream = stream_for()

    utterances = await collect(
        stream, interim("레디스", 0.0, 0.5), final("레디스로 캐시를", 0.0, 1.0)
    )

    assert [u.content for u in utterances] == ["레디스로 캐시를"]
    assert stream.interim_seen == 1
    assert stream.rejected == []


async def test_non_transcript_events_are_ignored() -> None:
    stream = stream_for()
    markers = [
        livekit_stt.SpeechEvent(type=event_type, alternatives=[])
        for event_type in (
            livekit_stt.SpeechEventType.START_OF_SPEECH,
            livekit_stt.SpeechEventType.END_OF_SPEECH,
            livekit_stt.SpeechEventType.RECOGNITION_USAGE,
        )
    ]

    assert await collect(stream, *markers) == []
    assert stream.rejected == []
    assert stream.interim_seen == 0


async def test_a_track_offset_moves_the_utterance_onto_the_session_clock() -> None:
    ordering = SessionOrdering()
    ordering.register("trk_interviewer")
    candidate = ordering.register("trk_candidate", offset_ms=30_000)
    stream = stream_for(ordering=candidate)

    utterances = await collect(stream, final("늦게 들어왔습니다", 1.0, 2.0))

    assert utterances[0].start_ms == 31_000
    assert utterances[0].end_ms == 32_000


async def test_two_tracks_interleave_on_one_session_timeline() -> None:
    """The whole point of sharing ``TrackOrdering`` with the Elice path."""

    ordering = SessionOrdering()
    interviewer = ordering.register("trk_interviewer")
    candidate = ordering.register("trk_candidate")

    questions = await collect(
        stream_for(
            track_id="trk_interviewer",
            speaker=SpeakerRole.INTERVIEWER,
            ordering=interviewer,
        ),
        final("캐시는 어떻게 붙였나요", 0.0, 2.0),
        final("왜 레디스였나요", 6.0, 7.0),
    )
    answers = await collect(
        stream_for(ordering=candidate),
        final("레디스를 썼습니다", 3.0, 5.0),
    )

    snapshot = TranscriptSnapshot(
        session_id="ses_test", utterances=[*answers, *questions]
    )
    assert [u.content for u in snapshot.final_utterances()] == [
        "캐시는 어떻게 붙였나요",
        "레디스를 썼습니다",
        "왜 레디스였나요",
    ]


async def test_ordering_for_a_different_track_is_refused() -> None:
    ordering = SessionOrdering().register("trk_interviewer")

    with pytest.raises(ValueError, match="trk_interviewer"):
        stream_for(track_id="trk_candidate", ordering=ordering)


async def test_word_timings_are_carried_through() -> None:
    words = [
        TimedString("레디스로", start_time=1.0, end_time=1.5, confidence=0.9),
        TimedString("캐시를", start_time=1.5, end_time=2.0, confidence=0.8),
    ]

    utterances = await collect(
        stream_for(), final("레디스로 캐시를", 1.0, 2.0, words=words)
    )

    assert [(w.seq, w.content, w.start_ms, w.end_ms) for w in utterances[0].words] == [
        (0, "레디스로", 1000, 1500),
        (1, "캐시를", 1500, 2000),
    ]
    assert utterances[0].words[0].confidence == pytest.approx(0.9)


async def test_words_without_usable_timing_are_dropped_not_guessed() -> None:
    """Giving an unaligned word the utterance's own span would read as timing."""

    words = [
        TimedString("레디스로", start_time=1.0, end_time=1.5),
        TimedString("캐시를", start_time=NOT_GIVEN, end_time=NOT_GIVEN),
        TimedString("붙였습니다", start_time=9.0, end_time=9.5),  # outside the span
        TimedString("   ", start_time=1.6, end_time=1.7),
    ]

    utterances = await collect(
        stream_for(), final("레디스로 캐시를 붙였습니다", 1.0, 2.0, words=words)
    )

    assert [w.content for w in utterances[0].words] == ["레디스로"]


async def test_word_confidence_outside_the_schema_range_becomes_none() -> None:
    words = [TimedString("레디스로", start_time=1.0, end_time=1.5, confidence=7.0)]

    utterances = await collect(stream_for(), final("레디스로", 1.0, 2.0, words=words))

    assert utterances[0].words[0].confidence is None


async def test_lag_is_measured_from_the_stream_clock_not_the_wall_clock() -> None:
    """``event.created_at`` is on no origin this track shares."""

    ticks = iter([100.0, 102.5])  # stream opened, then the final arrived
    stream = stream_for(clock=lambda: next(ticks))

    await collect(stream, final("레디스로 캐시를", 0.0, 2.0))

    assert [t.lag_ms for t in stream.timings] == [500]
    assert stream.timings[0].utterance_id == "utt_trk_candidate_0000"


async def test_rejections_keep_the_span_and_the_reason_and_no_text() -> None:
    """A rejected event's text is unvetted, and NO_TIMING's is actively wrong."""

    stream = stream_for()

    await collect(stream, final("시간이 없는 본문", 0.0, 0.0))

    rejected = stream.rejected[0]
    assert rejected.reason == REASON_NO_TIMING
    assert not any("본문" in str(value) for value in vars(rejected).values())


def test_build_stt_refuses_a_model_the_measurements_do_not_cover() -> None:
    settings = Settings(
        cartesia_api_key="sk-not-a-real-key", cartesia_stt_model="ink-2"
    )

    with pytest.raises(ValueError, match="ink-whisper"):
        build_stt(settings)


def test_build_stt_refuses_a_missing_key() -> None:
    with pytest.raises(ValueError, match="CARTESIA_API_KEY"):
        build_stt(Settings(cartesia_api_key=""))
