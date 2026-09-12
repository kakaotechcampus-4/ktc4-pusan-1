"""Segmentation decides where to cut and what is not worth a request at all."""

import array

import pytest

from audio import RATE, silence, tone
from irya_ai.stt.segmentation import (
    CutReason,
    NoiseFloor,
    SegmentationConfig,
    StreamSegmenter,
    frame_rms,
)


def test_pause_longer_than_the_rule_ends_a_segment() -> None:
    segmenter = StreamSegmenter()

    emitted = segmenter.push(tone(1500) + silence(800) + tone(500))

    assert [s.reason for s in emitted] == [CutReason.PAUSE]
    assert emitted[0].start_ms == 0
    # Cut in the middle of the pause, so the speech keeps its trailing silence.
    assert 1800 <= emitted[0].end_ms <= 2000


def test_pause_shorter_than_the_rule_does_not_cut() -> None:
    segmenter = StreamSegmenter(SegmentationConfig(max_segment_ms=30000))

    emitted = segmenter.push(tone(1000) + silence(400) + tone(1000))

    assert emitted == []


def test_long_speech_is_force_cut_at_the_cap() -> None:
    segmenter = StreamSegmenter(SegmentationConfig(quiet_search_ms=100))

    emitted = segmenter.push(tone(12000))

    assert [s.reason for s in emitted] == [CutReason.FORCED, CutReason.FORCED]
    assert all(s.duration_ms <= 5000 for s in emitted)
    # Segments tile the stream: a forced cut must not drop audio between them.
    assert emitted[0].end_ms == emitted[1].start_ms


def test_forced_cut_moves_to_the_quietest_point_in_the_window() -> None:
    """A dip between words is a safer cut than the 5s mark itself."""

    config = SegmentationConfig(quiet_search_ms=1500)
    segmenter = StreamSegmenter(config)

    # A 200ms dip at 4.0s, well inside the search window that ends at 5.0s.
    audio = tone(4000) + tone(200, amplitude=300) + tone(3000)
    emitted = segmenter.push(audio)

    assert emitted[0].reason is CutReason.FORCED
    assert 4000 <= emitted[0].end_ms <= 4200


def test_silence_is_never_sent() -> None:
    """Whisper answers near-silence with a stock sentence; the call is waste."""

    segmenter = StreamSegmenter()

    emitted = segmenter.push(silence(9000))
    emitted += segmenter.flush()

    assert emitted == []


def test_a_sliver_is_merged_into_the_next_segment_not_dropped() -> None:
    config = SegmentationConfig(min_segment_ms=1000, max_segment_ms=30000)
    segmenter = StreamSegmenter(config)

    # 300ms of speech, a qualifying pause, then a full turn.
    emitted = segmenter.push(tone(300) + silence(800) + tone(2000) + silence(800))

    assert len(emitted) == 1
    assert emitted[0].start_ms == 0
    assert emitted[0].duration_ms >= 2000


def test_flush_releases_the_tail() -> None:
    segmenter = StreamSegmenter()

    assert segmenter.push(tone(2000)) == []
    tail = segmenter.flush()

    assert [s.reason for s in tail] == [CutReason.FLUSH]
    assert tail[0].duration_ms == pytest.approx(2000, abs=40)


def test_partial_frames_are_buffered_across_pushes() -> None:
    segmenter = StreamSegmenter()
    audio = tone(2000)

    for offset in range(0, len(audio), 111):  # deliberately not a frame multiple
        segmenter.push(audio[offset : offset + 111])

    assert segmenter.elapsed_ms == pytest.approx(2000, abs=40)


def test_segments_carry_their_own_audio() -> None:
    segmenter = StreamSegmenter()

    emitted = segmenter.push(tone(1500) + silence(800) + tone(1500))
    segment = emitted[0]

    assert len(segment.pcm) == RATE * segment.duration_ms // 1000 * 2


def test_frame_rms_is_zero_for_silence() -> None:
    assert frame_rms(array.array("h", [0] * 320)) == 0.0
    assert frame_rms(array.array("h")) == 0.0


def test_noise_floor_falls_faster_than_it_rises() -> None:
    falling = NoiseFloor(initial=1000.0)
    rising = NoiseFloor(initial=1000.0)

    falling.update(0.0, voiced=False)
    rising.update(2000.0, voiced=False)

    assert 1000.0 - falling.value > rising.value - 1000.0


def test_speech_never_raises_the_noise_floor() -> None:
    floor = NoiseFloor(initial=100.0)

    for _ in range(1000):
        floor.update(6000.0, voiced=True)

    assert floor.value == 100.0


def test_a_long_turn_is_not_chopped_by_a_phantom_pause() -> None:
    """Regression: a threshold that tracked speech made the segmenter deaf.

    With the noise floor following every frame, twenty seconds of continuous
    speech walked the threshold above the speech itself and the silence rule
    fired at 1.4s, cutting the speaker off mid-sentence.
    """

    segmenter = StreamSegmenter(SegmentationConfig(max_segment_ms=30000))

    assert segmenter.push(tone(20000)) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_rate": 0},
        {"frame_ms": 0},
        {"min_segment_ms": 6000, "max_segment_ms": 5000},
        {"quiet_search_ms": 5000, "max_segment_ms": 5000},
        {"noise_margin": 0.5},
    ],
)
def test_invalid_configuration_is_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        SegmentationConfig(**kwargs)
