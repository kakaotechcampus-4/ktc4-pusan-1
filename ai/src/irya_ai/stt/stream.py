"""The live path: PCM in, utterances out (TechSpec F2).

Segmentation, transcription and the guards are separate pieces; this is what
connects them. Audio is pushed in as it arrives, cut into segments that are
worth a request, transcribed with a few requests in flight at once, and
released as :class:`~irya_ai.schemas.transcript.Utterance` in the order they
were spoken - never in the order the responses happen to come back, because
out-of-order text is worse to read than slightly later text.

Segments that the guards reject never become utterances. They are logged with
their reason so a gap in a transcript can be explained afterwards.
"""

import asyncio
import dataclasses
import io
import logging
import wave
from collections import deque
from collections.abc import AsyncIterator

from irya_ai.schemas.transcript import PassType, SpeakerRole, Utterance
from irya_ai.stt.elice import EliceSttClient, SttError, Transcription, is_hallucinated
from irya_ai.stt.segmentation import (
    PCM_WIDTH,
    AudioSegment,
    CutReason,
    SegmentationConfig,
    StreamSegmenter,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class RejectedSegment:
    """Why a span of audio produced no utterance.

    Deliberately holds no PCM. An interview is long, rejections accumulate for
    the whole of it, and the span and the reason are all that is needed to
    explain a gap in a transcript afterwards - keeping the audio would mean
    holding interview recordings in memory for a session at a time, and the
    project has no agreed retention policy to hold them under.
    """

    index: int
    start_ms: int
    end_ms: int
    cut_reason: CutReason
    reason: str


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw mono 16-bit PCM in a WAV container, which is what the API takes."""

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(PCM_WIDTH)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def silent_probe(sample_rate: int = 16000, duration_ms: int = 1000) -> bytes:
    """A WAV of silence, for warming the deployment before an interview starts."""

    return wav_bytes(
        b"\x00" * (sample_rate * duration_ms // 1000 * PCM_WIDTH), sample_rate
    )


class TranscriptionStream:
    """One participant's audio track, transcribed as it is spoken.

    Push audio with :meth:`push`, call :meth:`close` when the track ends, and
    iterate the instance to receive utterances in spoken order.
    """

    def __init__(
        self,
        client: EliceSttClient,
        *,
        session_id: str,
        track_id: str,
        speaker: SpeakerRole,
        config: SegmentationConfig | None = None,
        max_concurrency: int = 3,
    ) -> None:
        self.client = client
        self.session_id = session_id
        self.track_id = track_id
        self.speaker = speaker
        self.segmenter = StreamSegmenter(config)
        self._limit = asyncio.Semaphore(max_concurrency)
        self._pending: deque[tuple[AudioSegment, asyncio.Task[Transcription]]] = deque()
        self._closed = False
        self._seq = 0
        self.rejected: list[RejectedSegment] = []

    def push(self, pcm: bytes) -> int:
        """Feed audio in. Returns how many segments were sent for transcription."""

        if self._closed:
            raise RuntimeError("cannot push into a closed stream")
        segments = self.segmenter.push(pcm)
        for segment in segments:
            self._schedule(segment)
        return len(segments)

    def close(self) -> int:
        """Stop accepting audio and send whatever is left in the buffer."""

        if self._closed:
            return 0
        self._closed = True
        segments = self.segmenter.flush()
        for segment in segments:
            self._schedule(segment)
        return len(segments)

    def _schedule(self, segment: AudioSegment) -> None:
        self._pending.append(
            (segment, asyncio.ensure_future(self._transcribe(segment)))
        )

    async def _transcribe(self, segment: AudioSegment) -> Transcription:
        async with self._limit:
            audio = wav_bytes(segment.pcm, self.segmenter.config.sample_rate)
            return await self.client.transcribe(
                audio, filename=f"seg_{segment.index:04d}.wav"
            )

    async def __aiter__(self) -> AsyncIterator[Utterance]:
        """Yield utterances in spoken order as their transcriptions arrive."""

        while self._pending:
            segment, task = self._pending.popleft()
            utterance = await self._resolve(segment, task)
            if utterance is not None:
                yield utterance

    async def drain(self) -> list[Utterance]:
        """Await every scheduled segment and return the utterances at once."""

        return [utterance async for utterance in self]

    async def _resolve(
        self, segment: AudioSegment, task: asyncio.Task[Transcription]
    ) -> Utterance | None:
        try:
            transcription = await task
        except SttError:
            logger.exception("segment %d could not be transcribed", segment.index)
            return self._reject(segment, "REQUEST_FAILED")

        if transcription.is_empty:
            return self._reject(segment, "EMPTY")
        if is_hallucinated(transcription, segment.duration_ms):
            # The model described more audio than it was given, so the text
            # is about audio that does not exist.
            return self._reject(segment, "TIMESTAMP_OVERRUN")

        utterance = Utterance(
            utterance_id=f"utt_{self.track_id}_{segment.index:04d}",
            session_id=self.session_id,
            track_id=self.track_id,
            speaker=self.speaker,
            seq=self._seq,
            pass_type=PassType.FINAL,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            content=transcription.text,
        )
        self._seq += 1
        return utterance

    def _reject(self, segment: AudioSegment, reason: str) -> None:
        logger.info(
            "dropped segment %d (%dms, cut=%s): %s",
            segment.index,
            segment.duration_ms,
            segment.reason.value,
            reason,
        )
        self.rejected.append(
            RejectedSegment(
                index=segment.index,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                cut_reason=segment.reason,
                reason=reason,
            )
        )
        return None
