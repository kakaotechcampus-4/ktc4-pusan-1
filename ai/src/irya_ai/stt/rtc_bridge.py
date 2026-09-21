"""LiveKit microphone tracks to Cartesia streaming STT.

This is the integration seam that the provider-only adapter in
``irya_ai.stt.cartesia`` deliberately leaves out. A room job owns one
``RoomTranscriber``. It subscribes to each human microphone track, asks the
LiveKit SDK for mono 16 kHz frames, pushes those frames into one Cartesia
stream per track, and publishes the resulting live caption to the interviewer.

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
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol

from livekit import rtc
from livekit.agents import stt as livekit_stt

from irya_ai.schemas.transcript import SpeakerRole, Utterance
from irya_ai.stt.cartesia import SAMPLE_RATE, CartesiaTranscriptionStream
from irya_ai.stt.session import SessionOrdering

logger = logging.getLogger(__name__)

ROOM_PREFIX = "interview_"
TRANSCRIPT_TOPIC = "irya.transcript.v1"
TRANSCRIPT_DESTINATION = SpeakerRole.INTERVIEWER.value
DEGRADED_REASON = "STT_UNAVAILABLE"


class StreamingSTT(Protocol):
    """The part of a LiveKit STT provider used by the bridge."""

    def stream(self) -> livekit_stt.SpeechStream: ...


UtteranceSink = Callable[[Utterance], Awaitable[None]]
ConverterFactory = Callable[[], CartesiaTranscriptionStream]


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


async def _pump_frames(
    frames: AsyncIterator[rtc.AudioFrame], stream: livekit_stt.SpeechStream
) -> None:
    try:
        async for frame in frames:
            stream.push_frame(frame)
    finally:
        # Give Cartesia the end-of-input signal so it can flush the final span.
        # If the provider task already failed, it may have closed the input.
        try:
            stream.end_input()
        except RuntimeError:
            pass


async def _emit_utterances(
    converter: CartesiaTranscriptionStream,
    events: AsyncIterable[livekit_stt.SpeechEvent],
    sink: UtteranceSink,
) -> None:
    async for utterance in converter.utterances(events):
        await sink(utterance)


async def _run_stream_tasks(
    *,
    frames: AsyncIterator[rtc.AudioFrame],
    provider_stream: livekit_stt.SpeechStream,
    converter: CartesiaTranscriptionStream,
    sink: UtteranceSink,
) -> None:
    """Run send and receive together, cancelling a dead opposite half."""

    pump = asyncio.create_task(
        _pump_frames(frames, provider_stream), name="cartesia-audio-pump"
    )
    receive = asyncio.create_task(
        _emit_utterances(converter, provider_stream, sink),
        name="cartesia-event-receiver",
    )
    tasks = {pump, receive}

    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if receive in done:
            # A provider disconnect must stop the otherwise long-lived audio
            # pump. Propagate its exception to the participant boundary below.
            await receive
            if not pump.done():
                pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
            return

        # Normal track completion: the pump's finally block calls end_input,
        # then the receiver is allowed to drain Cartesia's last FINAL.
        await pump
        await receive
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def transcribe_audio_frames(
    *,
    frames: AsyncIterable[rtc.AudioFrame],
    stt: StreamingSTT,
    converter_factory: ConverterFactory,
    sink: UtteranceSink,
) -> CartesiaTranscriptionStream | None:
    """Push one subscribed track into Cartesia until either side ends.

    The provider stream is created only after LiveKit yields its first frame.
    This avoids opening an idle provider clock when a participant is connected
    but still muted. The converter factory runs at that same boundary so its
    caller can place the track accurately on the room timeline.
    """

    frame_iterator = aiter(frames)
    try:
        first_frame = await anext(frame_iterator)
    except StopAsyncIteration:
        return None

    converter = converter_factory()
    converter.start()
    async with stt.stream() as provider_stream:
        provider_stream.push_frame(first_frame)
        await _run_stream_tasks(
            frames=frame_iterator,
            provider_stream=provider_stream,
            converter=converter,
            sink=sink,
        )
    return converter


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
    """Own one room's clock, ordering, provider, and live-caption sink."""

    def __init__(
        self,
        *,
        room: rtc.Room,
        session_id: str,
        stt: StreamingSTT,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.room = room
        self.session_id = session_id
        self.stt = stt
        self.ordering = SessionOrdering()
        self.sink = LiveKitTextSink(room)
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
            audio_stream = rtc.AudioStream.from_track(
                track=track,
                sample_rate=SAMPLE_RATE,
                num_channels=1,
            )

            def converter_factory(
                track_id: str = track_id,
            ) -> CartesiaTranscriptionStream:
                ordering = self.ordering.register(
                    track_id, offset_ms=self._track_offset_ms()
                )
                return CartesiaTranscriptionStream(
                    session_id=self.session_id,
                    track_id=track_id,
                    speaker=speaker,
                    ordering=ordering,
                    clock=self._monotonic_clock,
                )

            try:
                converter = await transcribe_audio_frames(
                    frames=_audio_frames(audio_stream),
                    stt=self.stt,
                    converter_factory=converter_factory,
                    sink=self.sink,
                )
                if converter is not None:
                    logger.info(
                        "microphone transcription ended track=%s speaker=%s "
                        "accepted=%d rejected=%d",
                        publication.sid,
                        speaker.value,
                        len(converter.timings),
                        len(converter.rejected),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                # The participant callback is isolated from the room job. A
                # provider or transport failure changes only transcript state.
                logger.exception(
                    "microphone transcription failed track=%s speaker=%s",
                    publication.sid,
                    speaker.value,
                )
                try:
                    await self.sink.degraded()
                except Exception:
                    logger.exception("failed to publish transcript degraded event")
                return
            finally:
                await audio_stream.aclose()
