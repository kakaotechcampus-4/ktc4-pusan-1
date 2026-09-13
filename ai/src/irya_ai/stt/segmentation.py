"""Where to cut a live audio stream before each STT request (TechSpec F2).

STT runs on chunks, and the chunk boundary is what costs accuracy. A cut
placed mid-syllable leaves Whisper a truncated fragment, which it completes
into a fluent but different sentence. Cutting this corpus exactly at the cap
turned "응답 시간을 60% 줄였습니다" into "응답. 시간을 60분." - the percentage
came back as a unit of time. That is the failure mode to design against: not
missing text, which is visible, but a confident wrong number, which is not.

Overlapping neighbours hides a bad cut by sending the same 300ms twice, but
then both transcripts contain it, and every response observed from this
deployment has carried segment-level timestamps only, so the duplicate could
not be located and removed afterwards. No overlap is therefore the starting
strategy rather than a proven ceiling - see :mod:`irya_ai.stt.elice` for what
was and was not established about word-level timings.

This module cuts on silence instead, and when a turn runs past the cap it
moves the forced cut to the quietest frame near the deadline.

What was measured, and how far it goes: on a TTS-read synthetic Korean
interview corpus (macOS ``say -v Yuna``, n=6 files, no human speech and no
interview data), at a 5s cap, moving the forced cut lowered character error
rate from 0.089 to 0.054 and took the checked facts from 25/28 to 27/28 - a
net gain of two rather than a strict improvement, since it recovered the
sentence above but lost a numeral elsewhere. That error rate is *disagreement
with a whole-file Whisper transcript of the same audio*, not error against a
human-corrected reference: both numbers move if the baseline transcript is
wrong. Raw runs are under ``stt-bench/``.

What was not measured: display lag. Moving a cut earlier shortens the audio
in one request, but it does not follow that text reaches a reader sooner -
the decision still waits for the full lookback window (see
:attr:`AudioSegment.decision_lag_ms`), and smaller segments mean more
requests competing for the same concurrency budget. :mod:`irya_ai.stt.stream`
instruments the stages end to end; no claim about a reader's screen is made
anywhere here, because nothing in this repository renders one yet.

Everything here is stdlib and deterministic: no model, no network, no file.
"""

import array
import dataclasses
from enum import StrEnum

PCM_WIDTH = 2  # 16-bit little-endian mono, the only format the STT layer accepts


class CutReason(StrEnum):
    """Why a segment ended. Carried through so failures stay attributable."""

    PAUSE = "PAUSE"
    FORCED = "FORCED"
    FLUSH = "FLUSH"


@dataclasses.dataclass(frozen=True)
class SegmentationConfig:
    """Knobs for :class:`StreamSegmenter`.

    Defaults trade accuracy against how long a segment is held before it is
    sent. On the corpus above, a 5s cap kept 27 of 28 checked facts and an 8s
    cap kept all 28, so the cap is the lever to move if a deployment would
    rather have the accuracy.

    The accompanying p95 figures - 6.6s at a 5s cap, 9.5s at 8s - are an
    author-reported proxy, computed as segment duration plus request latency
    from the harness runs under ``stt-bench/runs/``. They are not measured
    display lag: they were taken from a standalone benchmark client rather
    than this code path, and they leave out the cut decision delay, the wait
    for an admission slot, the wait behind an older segment still in flight,
    and every step past this process, of which the largest - a browser - does
    not exist yet.

    They are not a lower bound either, in this deployment or any other. The
    stages they omit only add time, but the figures come from different runs
    than any given session will be, and provider latency is not a constant to
    add stages to: a cold worker, a different concurrency, a different length
    of audio or a busier deployment all move the request itself. A later run
    can be faster or slower than these numbers for reasons that have nothing
    to do with what they left out. Treat them as what one author measured on
    one set of runs, not as a floor and not as a latency any reader
    experienced.

    ``noise_margin`` and ``absolute_floor`` set the silence threshold. A live
    stream has no peak to normalise against, so the threshold tracks a running
    noise floor instead, and never drops below ``absolute_floor`` so that a
    digitally silent stream is not read as continuous speech.
    """

    sample_rate: int = 16000
    frame_ms: int = 20
    silence_ms: int = 700
    max_segment_ms: int = 5000
    quiet_search_ms: int = 1500
    min_segment_ms: int = 1000
    noise_margin: float = 4.0
    absolute_floor: float = 120.0

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.frame_ms <= 0:
            raise ValueError("sample_rate and frame_ms must be positive")
        if self.min_segment_ms > self.max_segment_ms:
            raise ValueError("min_segment_ms must not exceed max_segment_ms")
        if self.quiet_search_ms >= self.max_segment_ms:
            raise ValueError("quiet_search_ms must be shorter than max_segment_ms")
        if self.noise_margin < 1.0 or self.absolute_floor < 0:
            raise ValueError("noise_margin must be >= 1 and absolute_floor >= 0")

    @property
    def frame_samples(self) -> int:
        return self.sample_rate * self.frame_ms // 1000

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * PCM_WIDTH


@dataclasses.dataclass(frozen=True)
class AudioSegment:
    """One span of audio ready to be sent to STT.

    ``start_ms`` and ``end_ms`` are measured from the first sample ever pushed
    *to this segmenter*, so segments from the same stream share a timeline and
    can be turned into utterances. Two tracks do not share it: each one starts
    counting at its own first sample, not at a shared recording clock. Putting
    two tracks on one timeline is :mod:`irya_ai.stt.session`'s job, not this
    module's.

    ``received_ms`` is where the stream head was when this segment was
    emitted, on the same timeline. It is never smaller than ``end_ms`` and is
    usually larger, because a forced cut is moved back to the quietest frame
    within the lookback window: the segmenter had to hear the whole window
    before it could decide where the segment ended. ``received_ms - end_ms``
    is that decision delay, and it is audio that was already captured and
    waiting while the cut was being chosen. It is carried here because it is
    the only place it is knowable, and anything measuring display lag that
    starts from ``end_ms`` undercounts by exactly this much.
    """

    index: int
    start_ms: int
    end_ms: int
    received_ms: int
    reason: CutReason
    pcm: bytes

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def decision_lag_ms(self) -> int:
        """Audio received past this segment's end before the cut was decided."""

        return self.received_ms - self.end_ms

    @property
    def first_sample_wait_ms(self) -> int:
        """How long this segment's first sample waited to be sent, at capture.

        Assumes real-time capture: that the stream was pushed in as it was
        spoken. Under that assumption this is the audio-side half of display
        lag, and the request is the other half.
        """

        return self.received_ms - self.start_ms


def frame_rms(samples: array.array) -> float:
    """Root mean square of one frame. Zero for an empty frame."""

    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


class NoiseFloor:
    """Running estimate of how loud the room is when nobody is speaking.

    Speech must never raise the estimate. If it does, a long uninterrupted
    turn walks the threshold up past its own level, every further frame reads
    as silence, and the segmenter cuts the speaker off mid-sentence at the
    silence rule. So the estimate only follows frames that are already
    believed to be non-speech, and drops quickly whenever the room gets
    quieter than the current guess.

    It starts at zero, i.e. assuming a quiet room, and :class:`StreamSegmenter`
    keeps ``absolute_floor`` underneath it. In a room noisier than that floor
    every frame reads as speech, the estimate never learns, and the pause rule
    stops firing - segments are then bounded by ``max_segment_ms`` alone.
    Sending too much audio is the safe direction to fail in; the alternative is
    discarding speech.
    """

    def __init__(self, initial: float = 0.0, *, fall: float = 0.25, rise: float = 0.02):
        self.value = initial
        self._fall = fall
        self._rise = rise

    def update(self, rms: float, *, voiced: bool) -> float:
        if rms < self.value:
            self.value += (rms - self.value) * self._fall
        elif not voiced:
            self.value += (rms - self.value) * self._rise
        return self.value


class StreamSegmenter:
    """Turns a live PCM stream into segments worth sending to STT.

    Push 16-bit mono PCM with :meth:`push`; it returns the segments that
    became complete. Call :meth:`flush` when the stream ends to release the
    trailing audio.

    Three guards decide what is worth a request at all:

    1. A span shorter than ``min_segment_ms`` is merged into the next one
       rather than dropped, because the sliver is still real speech.
    2. A span with no voiced frame is never sent. Whisper answers near-silence
       with a stock sentence - in testing, a subtitle-credits line - and the
       call is wasted either way.
    3. Some of what slips past those is caught after the response comes
       back, by :func:`irya_ai.stt.elice.is_hallucinated` - but only the
       shape it looks for, a span running past the audio. Nothing here
       detects a fabricated sentence that keeps to a plausible span.
    """

    def __init__(self, config: SegmentationConfig | None = None) -> None:
        self.config = config or SegmentationConfig()
        self._pending = bytearray()  # audio of the segment being built
        self._carry = bytearray()  # bytes of an incomplete trailing frame
        self._energies: list[float] = []  # rms per frame of _pending
        self._voiced: list[bool] = []
        self._floor = NoiseFloor()
        self._silence_frames = 0
        self._index = 0
        self._start_ms = 0
        self._elapsed_ms = 0

    @property
    def elapsed_ms(self) -> int:
        """Position of the stream head, in ms since the first pushed sample."""

        return self._elapsed_ms

    def push(self, pcm: bytes) -> list[AudioSegment]:
        """Feed audio in. Returns segments that are complete, oldest first."""

        cfg = self.config
        self._carry.extend(pcm)
        usable = len(self._carry) - len(self._carry) % cfg.frame_bytes
        if not usable:
            return []
        chunk, self._carry = (
            bytes(self._carry[:usable]),
            bytearray(self._carry[usable:]),
        )

        segments = []
        for offset in range(0, usable, cfg.frame_bytes):
            frame = chunk[offset : offset + cfg.frame_bytes]
            segments.extend(self._consume_frame(frame))
        return segments

    def flush(self) -> list[AudioSegment]:
        """Close the stream: emit the trailing audio, padding the last frame."""

        cfg = self.config
        if self._carry:
            padding = cfg.frame_bytes - len(self._carry)
            frame = bytes(self._carry) + b"\x00" * padding
            self._carry.clear()
            emitted = self._consume_frame(frame)
        else:
            emitted = []
        tail = self._emit(len(self._energies), CutReason.FLUSH)
        return emitted + ([tail] if tail else [])

    def _consume_frame(self, frame: bytes) -> list[AudioSegment]:
        cfg = self.config
        samples = array.array("h")
        samples.frombytes(frame)
        rms = frame_rms(samples)
        threshold = max(cfg.absolute_floor, self._floor.value * cfg.noise_margin)
        voiced = rms >= threshold
        self._floor.update(rms, voiced=voiced)

        self._pending.extend(frame)
        self._energies.append(rms)
        self._voiced.append(voiced)
        self._elapsed_ms += cfg.frame_ms
        self._silence_frames = 0 if voiced else self._silence_frames + 1

        span_ms = len(self._energies) * cfg.frame_ms
        if self._silence_frames * cfg.frame_ms >= cfg.silence_ms:
            # Cut in the middle of the pause: the speech on either side keeps
            # the breathing room that stops Whisper completing a fragment.
            keep = len(self._energies) - self._silence_frames // 2
            segment = self._emit(keep, CutReason.PAUSE)
            return [segment] if segment else []
        if span_ms >= cfg.max_segment_ms:
            segment = self._emit(self._quietest_frame(), CutReason.FORCED)
            return [segment] if segment else []
        return []

    def _quietest_frame(self) -> int:
        """Index to cut at: the least loud frame within the search window.

        Even the dip between two words is a better place to cut than the
        middle of a syllable, and the window is bounded so the segment cannot
        shrink below ``min_segment_ms``.
        """

        cfg = self.config
        total = len(self._energies)
        earliest = max(
            cfg.min_segment_ms // cfg.frame_ms,
            total - cfg.quiet_search_ms // cfg.frame_ms,
        )
        if earliest >= total:
            return total
        return min(range(earliest, total), key=lambda i: self._energies[i])

    def _emit(self, frame_count: int, reason: CutReason) -> AudioSegment | None:
        """Take the first ``frame_count`` frames as a segment, keep the rest.

        Returns ``None`` when the span is not worth a request - too short, or
        with no voiced frame in it - and in that case the audio stays in the
        buffer so the next segment carries it instead of losing it.
        """

        cfg = self.config
        frame_count = max(0, min(frame_count, len(self._energies)))
        span_ms = frame_count * cfg.frame_ms
        if not frame_count:
            return None

        voiced = self._voiced[:frame_count]
        if span_ms < cfg.min_segment_ms and reason is not CutReason.FLUSH:
            self._silence_frames = 0
            return None
        if not any(voiced):
            self._drop(frame_count)
            return None

        pcm = bytes(self._pending[: frame_count * cfg.frame_bytes])
        segment = AudioSegment(
            index=self._index,
            start_ms=self._start_ms,
            end_ms=self._start_ms + span_ms,
            received_ms=self._elapsed_ms,
            reason=reason,
            pcm=pcm,
        )
        self._index += 1
        self._drop(frame_count)
        return segment

    def _drop(self, frame_count: int) -> None:
        cfg = self.config
        del self._pending[: frame_count * cfg.frame_bytes]
        del self._energies[:frame_count]
        del self._voiced[:frame_count]
        self._start_ms += frame_count * cfg.frame_ms
        self._silence_frames = 0
