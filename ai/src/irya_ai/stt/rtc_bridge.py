"""LiveKit microphone tracks to the Whisper live path (TechSpec F2).

This is the seam between the room and :mod:`irya_ai.stt.stream`. A room job
owns one :class:`RoomTranscriber`. It subscribes to each human microphone
track, asks the LiveKit SDK for mono 16 kHz frames, pushes their PCM into one
:class:`~irya_ai.stt.stream.TranscriptionStream` per track, and hands every
utterance that comes out to the sinks it was given - by default the live
caption for the interviewer.

The STT is Elice Whisper over HTTP, cut into pause-delimited segments by the
stream. That decision - the model the project provides, for the MVP - was
taken on 2026-09-22 and is why the streaming provider this module was first
written against (#67) is not here. Nothing in this file knows which model is
behind the client; it knows the stream's ``push``/``close``/iterate shape.

The live caption travels over a LiveKit text stream rather than through a new
IRYA HTTP/WebSocket service. That keeps the backend out of the media path and
lets an STT failure remain independent from the call. Text streams are not
persistent, so this module is *only* the live display path. Recording-backed
transcription and post-interview storage remain separate work.
"""

import asyncio
import json
import logging
import time
from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Sequence,
)
from datetime import UTC, datetime
from functools import partial
from typing import Protocol

from livekit import rtc

from irya_ai.schemas.transcript import SpeakerRole, Utterance
from irya_ai.stt.elice import EliceSttClient
from irya_ai.stt.segmentation import SegmentationConfig
from irya_ai.stt.session import SessionOrdering
from irya_ai.stt.stream import TranscriptionStream

logger = logging.getLogger(__name__)

ROOM_PREFIX = "interview_"
TRANSCRIPT_TOPIC = "irya.transcript.v1"
TRANSCRIPT_DESTINATION = SpeakerRole.INTERVIEWER.value
DEGRADED_REASON = "STT_UNAVAILABLE"

# What the segmenter expects, and therefore what the room is asked to deliver.
# ``AudioStream.from_track`` resamples and downmixes to this on the SDK side,
# so a frame arriving in any other shape is a programming error, not audio.
SAMPLE_RATE = SegmentationConfig().sample_rate
NUM_CHANNELS = 1


UtteranceSink = Callable[[Utterance], Awaitable[None]]


class TranscribingStream(Protocol):
    """What the bridge needs from :class:`~irya_ai.stt.stream.TranscriptionStream`.

    Named here so a test can stand in a fake without an HTTP transport, and so
    the bridge states what it relies on: audio goes in with ``push``, ``close``
    says no more is coming, iterating yields utterances in spoken order until
    the closed stream runs dry, and ``aclose`` abandons whatever is in flight.
    """

    def push(self, pcm: bytes) -> int: ...

    def close(self) -> int: ...

    async def aclose(self) -> None: ...

    def __aiter__(self) -> AsyncIterator[Utterance]: ...


StreamFactory = Callable[[], TranscribingStream]


def session_id_from_room(room_name: str) -> str | None:
    """Recover the API session id from an IRYA LiveKit room name."""

    if not room_name.startswith(ROOM_PREFIX):
        return None
    return room_name[len(ROOM_PREFIX) :] or None


def speaker_from_identity(identity: str) -> SpeakerRole | None:
    """Map only the two human identities issued by the backend."""

    try:
        return SpeakerRole(identity)
    except ValueError:
        return None


def transcript_event_json(utterance: Utterance) -> str:
    """Map the AI utterance to the frontend's existing ``StreamEvent`` shape."""

    return json.dumps(
        {
            "type": "transcript.delta",
            "utteranceId": utterance.utterance_id,
            "speaker": utterance.speaker.value,
            "text": utterance.content,
            "at": utterance.start_ms / 1000,
            "final": utterance.is_final,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def degraded_event_json(reason: str = DEGRADED_REASON) -> str:
    """A frontend event that stops the transcript UI, not the media call."""

    return json.dumps(
        {"type": "stream.degraded", "reason": reason}, separators=(",", ":")
    )


class LiveKitTextSink:
    """Deliver live transcript events to the interviewer over the room."""

    def __init__(
        self,
        room: rtc.Room,
        *,
        destination_identity: str = TRANSCRIPT_DESTINATION,
    ) -> None:
        # Job entrypoints must register participant callbacks before connecting.
        # ``room.local_participant`` is unavailable at that point, so resolve it
        # only when there is an event to send (after ``ctx.connect``).
        self._room = room
        self._destination_identity = destination_identity

    async def __call__(self, utterance: Utterance) -> None:
        await self._send(transcript_event_json(utterance))

    async def degraded(self, reason: str = DEGRADED_REASON) -> None:
        await self._send(degraded_event_json(reason))

    async def _send(self, payload: str) -> None:
        # The candidate must not receive live captions: seeing their answer
        # change while speaking can influence it. Human tokens cannot publish
        # data, so this server-side participant is the only stream producer.
        await self._room.local_participant.send_text(
            payload,
            topic=TRANSCRIPT_TOPIC,
            destination_identities=[self._destination_identity],
        )


def frame_pcm(frame: rtc.AudioFrame) -> bytes:
    """The 16-bit mono PCM the segmenter takes, or a refusal.

    ``AudioFrame.data`` is a memoryview of native-endian ``int16``, which is
    little-endian on every platform this runs on and exactly the layout
    :mod:`irya_ai.stt.segmentation` reads.
    """

    if frame.sample_rate != SAMPLE_RATE or frame.num_channels != NUM_CHANNELS:
        raise ValueError(
            f"expected {SAMPLE_RATE} Hz mono audio, got "
            f"{frame.sample_rate} Hz x{frame.num_channels}"
        )
    return frame.data.tobytes()


async def _pump_frames(
    frames: AsyncIterator[rtc.AudioFrame], stream: TranscribingStream
) -> None:
    try:
        async for frame in frames:
            stream.push(frame_pcm(frame))
    finally:
        # The track ended, or the pump was cancelled from under it. Either
        # way the tail in the segmenter's buffer is real speech: ``close``
        # sends it and lets the consumer drain what it produces. A stream the
        # consumer has already abandoned refuses this, and that is fine.
        try:
            stream.close()
        except RuntimeError:
            pass


async def _emit_utterances(
    stream: TranscribingStream, sinks: Sequence[UtteranceSink]
) -> None:
    async for utterance in stream:
        for sink in sinks:
            await sink(utterance)
        # The id, the speaker and the span - never the text. Interview speech
        # does not belong in an application log, and the span is enough to
        # match this line against the segment timings summarised at the end.
        logger.info(
            "caption delivered utterance=%s speaker=%s %d-%dms chars=%d",
            utterance.utterance_id,
            utterance.speaker.value,
            utterance.start_ms,
            utterance.end_ms,
            len(utterance.content),
        )


def _percentile(values: Sequence[int], fraction: float) -> int | None:
    """Nearest-rank percentile, or ``None`` when there is nothing to rank."""

    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, round(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def lag_summary(stream: TranscriptionStream) -> str:
    """p50/p95 of first-sample-to-release, for the end-of-track log line.

    :attr:`~irya_ai.stt.stream.SegmentTiming.source_to_release_ms` assumes
    real-time capture, which a live track is, and stops at the consumer; the
    hop to the interviewer's screen is not in this process. It is the figure
    the team asked to see before deciding whether the Whisper path is fast
    enough, so it is measured and logged here rather than judged.
    """

    lags = [
        lag
        for t in stream.timings
        if t.outcome == "RELEASED" and (lag := t.source_to_release_ms) is not None
    ]
    p50 = _percentile(lags, 0.5)
    p95 = _percentile(lags, 0.95)
    if p50 is None or p95 is None:
        return "lag n=0"
    return f"lag n={len(lags)} p50={p50}ms p95={p95}ms"


async def _run_stream_tasks(
    *,
    frames: AsyncIterator[rtc.AudioFrame],
    stream: TranscribingStream,
    sinks: Sequence[UtteranceSink],
) -> None:
    """Run send and receive together, cancelling a dead opposite half.

    Whatever ends this - the track running out, a sink or the stream raising,
    a cancel from the participant boundary - the stream is abandoned at the
    end, which after a normal drain is a no-op and otherwise cancels the STT
    requests still in flight so none is left to be reported by the loop.
    """

    pump = asyncio.create_task(_pump_frames(frames, stream), name="stt-audio-pump")
    receive = asyncio.create_task(
        _emit_utterances(stream, sinks), name="stt-utterance-receiver"
    )
    tasks = {pump, receive}

    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if receive in done:
            # The consumer stopped first: a sink or the stream raised. That
            # must stop the otherwise long-lived audio pump. Propagate the
            # exception to the participant boundary below.
            await receive
            if not pump.done():
                pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
            return

        # Normal track completion: the pump's finally block closed the
        # stream, so the receiver ends once the last segment is released.
        await pump
        await receive
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await stream.aclose()


async def transcribe_audio_frames(
    *,
    frames: AsyncIterable[rtc.AudioFrame],
    stream_factory: StreamFactory,
    sinks: Sequence[UtteranceSink],
) -> TranscribingStream | None:
    """Push one subscribed track through the STT stream until either side ends.

    The stream is created only after LiveKit yields its first frame. A
    participant who is connected but still muted then costs nothing, and the
    factory runs at the moment audio actually starts, so its caller can place
    the track on the room timeline from that moment rather than from
    subscription.
    """

    frame_iterator = aiter(frames)
    try:
        first_frame = await anext(frame_iterator)
    except StopAsyncIteration:
        return None

    stream = stream_factory()
    stream.push(frame_pcm(first_frame))
    await _run_stream_tasks(frames=frame_iterator, stream=stream, sinks=sinks)
    return stream


def _matching_microphone(
    publication: rtc.RemoteTrackPublication,
    *,
    seen: set[str],
) -> bool:
    return (
        publication.sid not in seen
        and publication.kind == rtc.TrackKind.KIND_AUDIO
        and publication.source == rtc.TrackSource.SOURCE_MICROPHONE
        and publication.subscribed
        and publication.track is not None
    )


async def wait_for_microphone(
    room: rtc.Room,
    participant: rtc.RemoteParticipant,
    *,
    seen: set[str],
) -> rtc.RemoteTrackPublication:
    """Wait for this participant's next subscribed microphone publication."""

    if not room.isconnected():
        raise RuntimeError("room is not connected")

    loop = asyncio.get_running_loop()
    result: asyncio.Future[rtc.RemoteTrackPublication] = loop.create_future()

    def on_track_subscribed(
        _track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        publisher: rtc.RemoteParticipant,
    ) -> None:
        if (
            publisher is participant
            and _matching_microphone(publication, seen=seen)
            and not result.done()
        ):
            result.set_result(publication)

    def on_participant_disconnected(publisher: rtc.RemoteParticipant) -> None:
        if publisher is participant and not result.done():
            result.set_exception(RuntimeError("participant disconnected"))

    def on_connection_state_changed(state: int) -> None:
        if state == rtc.ConnectionState.CONN_DISCONNECTED and not result.done():
            result.set_exception(RuntimeError("room disconnected"))

    room.on("track_subscribed", on_track_subscribed)
    room.on("participant_disconnected", on_participant_disconnected)
    room.on("connection_state_changed", on_connection_state_changed)
    try:
        for publication in participant.track_publications.values():
            if _matching_microphone(publication, seen=seen):
                return publication
        return await result
    finally:
        room.off("track_subscribed", on_track_subscribed)
        room.off("participant_disconnected", on_participant_disconnected)
        room.off("connection_state_changed", on_connection_state_changed)


async def _audio_frames(stream: rtc.AudioStream) -> AsyncIterator[rtc.AudioFrame]:
    async for event in stream:
        yield event.frame


class RoomTranscriber:
    """Own one room's clock, ordering, STT client and utterance sinks.

    ``sinks`` receive every utterance in order, one after the other; the
    default is the interviewer's live caption alone. A sink that raises ends
    that track's transcription and sends ``stream.degraded`` - isolating one
    sink's failure from the others is the fan-out's job (#83), not this
    class's.

    One :class:`~irya_ai.stt.stream.TranscriptionStream` is opened per
    microphone track, all of them sharing ``client``. With the stream's
    default of three requests in flight, a two-person room puts at most six on
    the STT deployment at once.
    """

    def __init__(
        self,
        *,
        room: rtc.Room,
        session_id: str,
        client: EliceSttClient,
        sinks: Sequence[UtteranceSink] | None = None,
        segmentation: SegmentationConfig | None = None,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.room = room
        self.session_id = session_id
        self.client = client
        self.segmentation = segmentation
        self.ordering = SessionOrdering()
        self.caption = LiveKitTextSink(room)
        self.sinks: list[UtteranceSink] = (
            list(sinks) if sinks is not None else [self.caption]
        )
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._origin_at: datetime | None = None
        self._initial_scan_complete = asyncio.Event()
        self._origin_ready = asyncio.Event()

    def initialize_origin(
        self, participants: Iterable[rtc.RemoteParticipant]
    ) -> datetime | None:
        """Pin live-caption t=0 to the earliest human join visible so far.

        A backend-created room can dispatch the worker before either person
        joins. An empty initial scan therefore deliberately leaves the origin
        unset; the first human participant callback pins it later.
        """

        if self._origin_at is not None:
            self._initial_scan_complete.set()
            return self._origin_at

        joined_at = [
            participant.joined_at
            for participant in participants
            if speaker_from_identity(participant.identity) is not None
            and participant.joined_at is not None
        ]
        if joined_at:
            self._origin_at = min(joined_at)
            self._origin_ready.set()
        self._initial_scan_complete.set()
        return self._origin_at

    def _track_offset_ms(self) -> int:
        if self._origin_at is None:
            raise RuntimeError("room transcript origin is not initialized")
        elapsed = self._wall_clock() - self._origin_at
        return max(0, round(elapsed.total_seconds() * 1000))

    def stream_for(self, track_id: str, speaker: SpeakerRole) -> TranscriptionStream:
        """A fresh stream for one track, placed on the session timeline now.

        Called when the track's first frame arrives, not when it is
        subscribed, so ``offset_ms`` is where the audio really starts.
        """

        ordering = self.ordering.register(track_id, offset_ms=self._track_offset_ms())
        return TranscriptionStream(
            self.client,
            session_id=self.session_id,
            track_id=track_id,
            speaker=speaker,
            config=self.segmentation,
            ordering=ordering,
            clock=self._monotonic_clock,
        )

    async def transcribe_participant(self, participant: rtc.RemoteParticipant) -> None:
        """Transcribe this human's microphone, including a later republish."""

        speaker = speaker_from_identity(participant.identity)
        if speaker is None:
            logger.info(
                "ignoring non-human participant identity=%s", participant.identity
            )
            return

        # Existing participant callbacks may start while ``ctx.connect`` is
        # still returning. Let the post-connect scan consider all of them
        # before one callback can choose t=0. If the room was empty then, the
        # first later human participant establishes the live-caption origin.
        await self._initial_scan_complete.wait()
        if self._origin_at is None:
            self.initialize_origin([participant])
        await self._origin_ready.wait()
        seen: set[str] = set()
        while self.room.isconnected():
            try:
                publication = await wait_for_microphone(
                    self.room, participant, seen=seen
                )
            except RuntimeError:
                return

            seen.add(publication.sid)
            track = publication.track
            if not isinstance(track, rtc.RemoteAudioTrack):
                continue

            track_id = publication.sid
            logger.info(
                "microphone subscribed track=%s speaker=%s session=%s",
                track_id,
                speaker.value,
                self.session_id,
            )
            audio_stream = rtc.AudioStream.from_track(
                track=track,
                sample_rate=SAMPLE_RATE,
                num_channels=NUM_CHANNELS,
            )

            try:
                stream = await transcribe_audio_frames(
                    frames=_audio_frames(audio_stream),
                    stream_factory=partial(self.stream_for, track_id, speaker),
                    sinks=self.sinks,
                )
                if isinstance(stream, TranscriptionStream):
                    logger.info(
                        "microphone transcription ended track=%s speaker=%s "
                        "segments=%d rejected=%d dropped=%d %s",
                        publication.sid,
                        speaker.value,
                        len(stream.timings),
                        len(stream.rejected),
                        len(stream.dropped_spans),
                        lag_summary(stream),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                # The participant callback is isolated from the room job. An
                # STT or delivery failure changes only transcript state; the
                # call and the recording go on. A single failed request is not
                # this - the stream absorbs those per segment - so reaching
                # here means the track's transcription is over.
                logger.exception(
                    "microphone transcription failed track=%s speaker=%s",
                    publication.sid,
                    speaker.value,
                )
                try:
                    await self.caption.degraded()
                except Exception:
                    logger.exception("failed to publish transcript degraded event")
                return
            finally:
                await audio_stream.aclose()
