"""Transcribe an interview again from its recording (``REALIGNED`` stage).

The live path cuts every turn at 5s so captions keep up, and the cut is where
accuracy goes (:mod:`irya_ai.stt.segmentation`). Once the interview is over
nothing is waiting for the text, so this pass runs the same STT over the
recorded audio with a cap near Whisper's own 30s window. Review and summary
are meant to read the result instead of the live draft.

Input is what the backend's recording step leaves behind (#112): one Opus
``.ogg`` per microphone track, named ``{identity}-{track_sid}`` by the egress,
and the instant each file's 0s stands for. The track sid is the live path's
``track_id`` too, so a realigned utterance names the same track as the live
one it replaces.

Placing a file on the session clock
-----------------------------------

The session origin is the earliest human participant joining (the backend's
LiveKit webhook), and the live path's ``startMs`` counts from it. A recording
starts when its egress pipeline does, a little later. So a track sits at
``started_ms - origin_ms`` on the session clock, which goes to
:class:`~irya_ai.stt.session.SessionOrdering` exactly like a live track's
offset. A file that starts *before* the origin - only possible through clock
skew between the egress and the webhook - has its head trimmed so its first
remaining sample is the origin, rather than the whole track being moved.

What this does not do
---------------------

- **Deliver.** The result is a :class:`TranscriptSnapshot` with
  ``stage=REALIGNED`` in memory. The backend's transcript socket has no stage
  field yet, and its reads default to ``LIVE``; how a realigned snapshot gets
  stored and preferred is a contract still to be agreed.
- **Match live utterance ids.** Segment boundaries differ from the live pass,
  so there is no one-to-one mapping to inherit an id from. Ids here carry an
  ``r`` before the index so a realigned utterance can never be mistaken for
  the live one with the same number (#151).
- **Fetch from S3 or decide when to run.** The caller hands over local files.
"""

import asyncio
import dataclasses
import logging
from collections.abc import Iterator
from pathlib import Path

import av

from irya_ai.schemas.transcript import (
    PassType,
    SpeakerRole,
    TranscriptSnapshot,
    TranscriptStage,
    Utterance,
)
from irya_ai.stt.elice import EliceSttClient, SttError, Transcription, is_hallucinated
from irya_ai.stt.segmentation import (
    PCM_WIDTH,
    AudioSegment,
    SegmentationConfig,
    StreamSegmenter,
)
from irya_ai.stt.session import SessionOrdering, TrackOrdering
from irya_ai.stt.stream import wav_bytes

logger = logging.getLogger(__name__)

#: Segmentation for a recording. Pauses still cut, so a turn stays one
#: utterance; only a turn running past 25s is forced, which keeps every request
#: inside Whisper's 30s window with room for the quiet-frame search.
REALIGN_SEGMENTATION = SegmentationConfig(max_segment_ms=25_000, quiet_search_ms=3_000)

#: Requests in flight at once. The deployment is shared with live interviews,
#: which cannot wait, so this pass stays polite rather than fast.
DEFAULT_CONCURRENCY = 2


class RealignError(RuntimeError):
    """A recording could not be read at all. ``code`` is safe to log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclasses.dataclass(frozen=True)
class RecordedTrack:
    """One microphone recording and where its 0s sits in wall-clock time."""

    path: Path
    track_id: str
    speaker: SpeakerRole
    #: Epoch ms of the file's first sample - the egress ``started_at``.
    started_ms: int

    @classmethod
    def from_egress(cls, path: Path, started_ns: int) -> "RecordedTrack":
        """Read speaker and track sid off the ``{identity}-{track_sid}`` name."""

        identity, sep, track_id = path.stem.partition("-")
        try:
            speaker = SpeakerRole(identity)
        except ValueError:
            raise RealignError("REALIGN_UNKNOWN_SPEAKER") from None
        if not sep or not track_id:
            raise RealignError("REALIGN_UNNAMED_TRACK")
        return cls(path, track_id, speaker, started_ns // 1_000_000)


@dataclasses.dataclass(frozen=True)
class DroppedSpan:
    """A segment that did not become an utterance, and why."""

    track_id: str
    start_ms: int
    end_ms: int
    #: ``EMPTY``, ``TIMESTAMP_OVERRUN`` or ``REQUEST_FAILED``.
    reason: str
    code: str | None = None


@dataclasses.dataclass(frozen=True)
class RealignResult:
    snapshot: TranscriptSnapshot
    dropped: list[DroppedSpan]

    @property
    def failed(self) -> list[DroppedSpan]:
        """Segments whose request failed. Their speech is missing, not absent."""

        return [d for d in self.dropped if d.reason == "REQUEST_FAILED"]

    @property
    def complete(self) -> bool:
        """Whether every segment got an answer.

        An incomplete result is missing speech that the live draft may still
        have, so it must not replace the draft. Run it again instead.
        """

        return not self.failed


def decode_pcm(path: Path, *, sample_rate: int) -> Iterator[bytes]:
    """16-bit mono PCM at ``sample_rate``, from the file's 0s onward.

    The egress fills a dropped connection with silence, so the file's own
    timeline is continuous; only a first frame stamped after 0s needs padding
    to keep sample count and time in step.
    """

    try:
        container = av.open(str(path))
    except (av.error.FFmpegError, OSError):
        raise RealignError("REALIGN_UNREADABLE") from None
    with container:
        if not container.streams.audio:
            raise RealignError("REALIGN_NO_AUDIO")
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
        first = True
        try:
            for frame in container.decode(stream):
                if first:
                    first = False
                    if frame.time and frame.time > 0:
                        yield b"\x00" * (round(frame.time * sample_rate) * PCM_WIDTH)
                for out in resampler.resample(frame):
                    yield bytes(out.planes[0])[: out.samples * PCM_WIDTH]
            for out in resampler.resample(None):
                yield bytes(out.planes[0])[: out.samples * PCM_WIDTH]
        except av.error.FFmpegError:
            raise RealignError("REALIGN_UNREADABLE") from None


def segment_track(
    track: RecordedTrack, *, trim_ms: int, config: SegmentationConfig
) -> list[AudioSegment]:
    """Cut one recording into requests, dropping its first ``trim_ms``.

    Blocking: decoding is CPU work, so callers run it in a thread.
    """

    segmenter = StreamSegmenter(config)
    skip = trim_ms * config.sample_rate // 1000 * PCM_WIDTH
    segments: list[AudioSegment] = []
    for pcm in decode_pcm(track.path, sample_rate=config.sample_rate):
        if skip:
            taken = min(skip, len(pcm))
            pcm, skip = pcm[taken:], skip - taken
        if pcm:
            segments.extend(segmenter.push(pcm))
    segments.extend(segmenter.flush())
    return segments


async def realign(
    stt: EliceSttClient,
    *,
    session_id: str,
    origin_ms: int,
    tracks: list[RecordedTrack],
    config: SegmentationConfig = REALIGN_SEGMENTATION,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> RealignResult:
    """Transcribe ``tracks`` onto the session clock that starts at ``origin_ms``.

    Interviewers register first so that, as on the live path, a question and
    an answer starting on the same millisecond sort question first.
    """

    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    ordering = SessionOrdering()
    gate = asyncio.Semaphore(concurrency)
    order = {SpeakerRole.INTERVIEWER: 0, SpeakerRole.CANDIDATE: 1}
    work: list[tuple[RecordedTrack, TrackOrdering, AudioSegment]] = []
    for track in sorted(tracks, key=lambda t: (order[t.speaker], t.started_ms)):
        offset_ms = track.started_ms - origin_ms
        placed = ordering.register(track.track_id, offset_ms=max(offset_ms, 0))
        segments = await asyncio.to_thread(
            segment_track, track, trim_ms=max(-offset_ms, 0), config=config
        )
        logger.info(
            "realign track=%s offset=%dms segments=%d",
            track.track_id,
            offset_ms,
            len(segments),
        )
        work += [(track, placed, s) for s in segments]

    async def transcribe(segment: AudioSegment) -> Transcription | SttError:
        async with gate:
            try:
                return await stt.transcribe(
                    wav_bytes(segment.pcm, config.sample_rate),
                    filename=f"seg_{segment.index:04d}.wav",
                )
            except SttError as exc:
                return exc

    answers = await asyncio.gather(*(transcribe(s) for _, _, s in work))

    utterances: list[Utterance] = []
    dropped: list[DroppedSpan] = []
    for (track, placed, segment), answer in zip(work, answers, strict=True):
        start_ms = placed.session_ms(segment.start_ms)
        end_ms = placed.session_ms(segment.end_ms)
        if isinstance(answer, SttError):
            reason, code = "REQUEST_FAILED", answer.code
        elif answer.is_empty:
            reason, code = "EMPTY", None
        elif is_hallucinated(answer, segment.duration_ms):
            reason, code = "TIMESTAMP_OVERRUN", None
        else:
            utterances.append(
                Utterance(
                    utterance_id=f"utt_{track.track_id}_r{segment.index:04d}",
                    session_id=session_id,
                    track_id=track.track_id,
                    speaker=track.speaker,
                    seq=placed.seq(segment.start_ms),
                    pass_type=PassType.FINAL,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    content=answer.text,
                )
            )
            continue
        dropped.append(DroppedSpan(track.track_id, start_ms, end_ms, reason, code))

    utterances.sort(key=lambda u: u.seq)
    snapshot = TranscriptSnapshot(
        session_id=session_id, stage=TranscriptStage.REALIGNED, utterances=utterances
    )
    return RealignResult(snapshot=snapshot, dropped=dropped)
