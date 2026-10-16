"""Deepgram streaming STT behind the bridge's stream shape (TechSpec F2).

The team chose Deepgram over Elice Whisper on 2026-10-11 for live captions.
This module is the minimal connection: it puts the LiveKit Deepgram plugin
behind the same ``push``/``close``/iterate shape
:class:`~irya_ai.stt.rtc_bridge.TranscribingStream` names, so the room, the
caption and the downstream consumers do not change.

The settings are the ones that were compared live
(``stt-bench/livekit-eval/live_compare.py``): ``nova-3`` in Korean,
``numerals``, 300 ms endpointing, a fixed keyterm list, and a Silero VAD that
asks Deepgram to finalize after 1.0 s of silence. Deepgram's own endpointing
does not close an utterance reliably on Korean pauses; finalizing on the
shorter 0.55 s VAD default dropped words said right after the flush.

What goes out
-------------

Only FINAL utterances. Every non-empty Deepgram final becomes one
:class:`~irya_ai.schemas.transcript.Utterance` with a fresh id. Interim
results are counted but not yielded: the frontend currently appends every
``transcript.delta`` that shares an id to the text it already shows, so a
revision under the same id would print twice. How interims should travel is
not agreed yet.

Billing
-------

Deepgram bills the WebSocket's lifetime, silence included, not only the
segments that held speech. The plugin reports that as
``RECOGNITION_USAGE``; :attr:`DeepgramTranscriptionStream.billed_audio_s`
adds it up so a measurement can compare it with Elice's per-segment audio.
"""

import asyncio
import dataclasses
import logging
import time
from collections.abc import AsyncIterator, Callable
from functools import cache

import aiohttp
from livekit import rtc
from livekit.agents import stt as lk_stt
from livekit.agents import vad as lk_vad

from irya_ai.config import Settings
from irya_ai.schemas.transcript import PassType, SpeakerRole, Utterance
from irya_ai.stt.session import TrackOrdering, solo_ordering

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
NUM_CHANNELS = 1
MODEL = "nova-3"
ENDPOINTING_MS = 300
# How long the VAD waits in silence before asking Deepgram to finalize.
FLUSH_SILENCE_S = 1.0

# Terms a resume or job description would hand Deepgram as keyterm prompting.
# Fixed for now; building the list from the interview's own documents is later
# work. It overlaps the benchmark's checked facts, so a keyterm-on accuracy
# figure is biased upward on those words.
KEYTERMS = (
    "API",
    "P95",
    "레디스",
    "TTL",
    "카프카",
    "롤백",
    "쿠버네티스",
    "오토스케일링",
    "인스턴스",
    "웹소켓",
    "로드밸런서",
    "유휴 타임아웃",
    "재연결",
    "N+1",
    "쿼리",
    "포스트그레스",
    "인덱스",
    "조인",
    "밀리초",
    "모니터링",
    "대시보드",
    "엘라스틱서치",
    "스프링 부트",
    "도커",
    "그라파나",
    "프로메테우스",
    "gRPC",
    "몽고DB",
)


class DeepgramNotConfigured(RuntimeError):
    """No Deepgram key: the same "leave the room" case as an unset Elice URL."""


def build_stt(
    settings: Settings, *, http_session: aiohttp.ClientSession | None = None
) -> lk_stt.STT:
    """The plugin STT with the compared settings.

    ``http_session`` is required outside a LiveKit job: the plugin otherwise
    looks for the job's shared session and raises when there is none.
    """

    from livekit.plugins import deepgram

    api_key = settings.deepgram_api_key.get_secret_value()
    if not api_key:
        raise DeepgramNotConfigured("DEEPGRAM_API_KEY is not set")
    return deepgram.STT(
        model=MODEL,
        language="ko",
        sample_rate=SAMPLE_RATE,
        numerals=True,
        keyterm=list(KEYTERMS),
        endpointing_ms=ENDPOINTING_MS,
        api_key=api_key,
        http_session=http_session,
    )


@cache
def flush_vad() -> lk_vad.VAD:
    """One Silero model per process, shared by every track's VAD stream."""

    from livekit.plugins import silero

    return silero.VAD.load(min_silence_duration=FLUSH_SILENCE_S)


@dataclasses.dataclass
class FinalTiming:
    """One released final, for the end-of-track log and for measurement.

    ``start_ms``/``end_ms`` are on the session clock, like the utterance.
    ``received_at`` is the monotonic clock when the final arrived.
    """

    utterance_id: str
    start_ms: int
    end_ms: int
    received_at: float
    interims_before: int


class DeepgramTranscriptionStream:
    """One microphone track through one Deepgram WebSocket.

    ``push`` never blocks: frames go into the plugin's channel and the VAD's.
    ``close`` ends the input; the plugin then sends Finalize and CloseStream,
    so the last utterance comes back even when the track ends without a pause
    long enough for the VAD to flush it. Iterating yields FINAL utterances
    until Deepgram closes the stream. ``aclose`` abandons what is in flight.
    """

    def __init__(
        self,
        stt: lk_stt.STT,
        *,
        session_id: str,
        track_id: str,
        speaker: SpeakerRole,
        ordering: TrackOrdering | None = None,
        vad: lk_vad.VAD | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_id = session_id
        self.track_id = track_id
        self.speaker = speaker
        self.ordering = ordering or solo_ordering(track_id)
        self._clock = clock
        self._stt_stream = stt.stream(language="ko")
        self._vad_stream = (vad or flush_vad()).stream()
        self._vad_task = asyncio.create_task(
            self._flush_on_silence(), name=f"stt-vad-{track_id}"
        )
        self._closed = False
        self._abandoned = False
        self._index = 0
        self._last_start_ms = -1
        self._interims = 0

        self.finals: list[FinalTiming] = []
        self.interims_seen = 0
        self.empty_finals = 0
        self.vad_flushes = 0
        self.billed_audio_s = 0.0
        self.pushed_samples = 0

    def push(self, pcm: bytes) -> int:
        """Feed 16 kHz mono PCM. Returns 0: nothing is refused per segment."""

        if self._closed:
            raise RuntimeError("cannot push into a closed stream")
        samples = len(pcm) // 2
        if samples == 0:
            return 0
        frame = rtc.AudioFrame(
            data=pcm,
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            samples_per_channel=samples,
        )
        self.pushed_samples += samples
        self._stt_stream.push_frame(frame)
        self._vad_stream.push_frame(frame)
        return 0

    def close(self) -> int:
        """No more audio. Deepgram finalizes what it holds and closes."""

        if self._closed:
            return 0
        self._closed = True
        # ``end_input`` flushes first, which the plugin turns into Finalize
        # before CloseStream: the tail is transcribed, not cut off.
        self._stt_stream.end_input()
        self._vad_stream.end_input()
        return 0

    async def aclose(self) -> None:
        """Abandon the stream and release the socket and the VAD."""

        if self._abandoned:
            return
        self._abandoned = True
        self._closed = True
        self._vad_task.cancel()
        await asyncio.gather(self._vad_task, return_exceptions=True)
        await self._stt_stream.aclose()
        await self._vad_stream.aclose()

    @property
    def audio_s(self) -> float:
        return self.pushed_samples / SAMPLE_RATE

    async def _flush_on_silence(self) -> None:
        async for event in self._vad_stream:
            if event.type != lk_vad.VADEventType.END_OF_SPEECH or self._closed:
                continue
            try:
                self._stt_stream.flush()
            except RuntimeError:
                return
            self.vad_flushes += 1

    async def __aiter__(self) -> AsyncIterator[Utterance]:
        async for event in self._stt_stream:
            if self._abandoned:
                return
            if event.type == lk_stt.SpeechEventType.RECOGNITION_USAGE:
                if event.recognition_usage is not None:
                    self.billed_audio_s += event.recognition_usage.audio_duration
            elif event.type == lk_stt.SpeechEventType.INTERIM_TRANSCRIPT:
                self.interims_seen += 1
                self._interims += 1
            elif event.type == lk_stt.SpeechEventType.FINAL_TRANSCRIPT:
                utterance = self._utterance(event)
                if utterance is not None:
                    yield utterance

    def _utterance(self, event: lk_stt.SpeechEvent) -> Utterance | None:
        alternative = event.alternatives[0] if event.alternatives else None
        text = alternative.text.strip() if alternative is not None else ""
        if alternative is None or not text:
            # ``Utterance.content`` must not be empty; an empty final is
            # Deepgram closing silence, not something anyone said.
            self.empty_finals += 1
            return None

        track_start = max(0, round(alternative.start_time * 1000))
        track_end = max(track_start, round(alternative.end_time * 1000))
        # ``seq`` must be unique within the track. Two finals never share a
        # first word, but a final without word timings reports 0.
        track_start = max(track_start, self._last_start_ms + 1)
        track_end = max(track_end, track_start)
        self._last_start_ms = track_start

        utterance = Utterance(
            utterance_id=f"utt_{self.track_id}_{self._index:04d}",
            session_id=self.session_id,
            track_id=self.track_id,
            speaker=self.speaker,
            seq=self.ordering.seq(track_start),
            pass_type=PassType.FINAL,
            start_ms=self.ordering.session_ms(track_start),
            end_ms=self.ordering.session_ms(track_end),
            content=text,
        )
        self._index += 1
        self.finals.append(
            FinalTiming(
                utterance_id=utterance.utterance_id,
                start_ms=utterance.start_ms,
                end_ms=utterance.end_ms,
                received_at=self._clock(),
                interims_before=self._interims,
            )
        )
        self._interims = 0
        return utterance


def summary(stream: DeepgramTranscriptionStream) -> str:
    """Counts for the end-of-track log line; never the text."""

    return (
        f"finals={len(stream.finals)} interims={stream.interims_seen} "
        f"empty={stream.empty_finals} flushes={stream.vad_flushes} "
        f"audio={stream.audio_s:.1f}s billed={stream.billed_audio_s:.1f}s"
    )
