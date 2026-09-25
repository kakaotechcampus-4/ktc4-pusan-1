"""The live path: PCM in, utterances out (TechSpec F2).

Segmentation, transcription and the guards are separate pieces; this is what
connects them. Audio is pushed in as it arrives, cut into segments that are
worth a request, transcribed with a few requests in flight at once, and
released as :class:`~irya_ai.schemas.transcript.Utterance` in the order they
were spoken - never in the order the responses happen to come back, because
out-of-order text is worse to read than slightly later text.

Producer and consumer are separate
----------------------------------

:meth:`~TranscriptionStream.push` and :meth:`~TranscriptionStream.close` are
the producer, called from wherever audio arrives. Iterating the stream is the
consumer. The two run at once and the consumer outlives the gaps: an open
stream with nothing queued *waits* for the next segment rather than ending,
and only :meth:`~TranscriptionStream.close` ends it - after everything still
queued has been drained. A stream has one consumer at a time, because two
would race for the same head of the queue and neither would see spoken order.

What is bounded, and what is not
--------------------------------

Requests in flight are capped by ``max_concurrency``, and segments waiting for
one by ``max_pending``. Those two caps bound the expensive things: queued PCM
and outstanding tasks grow with the depth of the queue, not with the length of
the session. Audio is live and the producer cannot be made to wait for the
network, so when the queue is full the incoming segment is dropped rather than
admitted - recorded as a rejection with its span, so the resulting gap in the
transcript is attributable. Nothing recovers that audio: this layer holds no
recording and there is nothing to re-send it from.

Per-segment metadata is not bounded, and is not meant to be. ``timings`` gains
an entry for every segment the stream sees and ``rejected`` one for every
segment refused; neither is ever trimmed, because both exist to be read after
the fact and a span dropped an hour ago is exactly what an audit asks about.
They carry no audio, but they do grow with the length of the session, so
bounding them is the caller's: one stream per interview, released when the
interview ends, or copy out what is needed and drop the stream.

Segments the guards reject never become utterances. They are logged with a
stable code and their span - never with a response body, transcript text or
the deployment URL - so a gap in a transcript can be explained afterwards
without the log becoming the thing that leaks.
"""

import asyncio
import dataclasses
import io
import logging
import time
import wave
from collections import deque
from collections.abc import AsyncIterator, Callable

from irya_ai.schemas.transcript import PassType, SpeakerRole, Utterance
from irya_ai.stt.elice import EliceSttClient, SttError, Transcription, is_hallucinated
from irya_ai.stt.segmentation import (
    PCM_WIDTH,
    AudioSegment,
    CutReason,
    SegmentationConfig,
    StreamSegmenter,
)
from irya_ai.stt.session import TrackOrdering, solo_ordering

logger = logging.getLogger(__name__)

# How many segments may wait for a request slot before further ones are
# dropped. At the 5s cap this is a couple of minutes of backlog and a few MB
# of PCM per track: large enough to ride out a slow deployment, small enough
# that a deployment which has stopped answering cannot take the process with
# it.
DEFAULT_MAX_PENDING = 16


@dataclasses.dataclass(frozen=True)
class RejectedSegment:
    """Why a span of audio produced no utterance.

    Deliberately holds no PCM. An interview is long, rejections accumulate for
    the whole of it, and the span and the reason are all that is needed to
    explain a gap in a transcript afterwards - keeping the audio would mean
    holding interview recordings in memory for a session at a time, and the
    project has no agreed retention policy to hold them under.

    ``reason`` is the coarse category: ``EMPTY``, ``TIMESTAMP_OVERRUN``,
    ``REQUEST_FAILED`` or ``OVERLOADED``. ``code`` carries the transcription
    error's stable code when there was one, so a malformed body and a refused
    key stay distinguishable without either being re-read from a log.

    Spans are on the session clock, the same one ``seq`` is built from.
    """

    index: int
    start_ms: int
    end_ms: int
    cut_reason: CutReason
    reason: str
    code: str | None = None


@dataclasses.dataclass
class SegmentTiming:
    """When each stage happened to one segment, as wall clock and as audio.

    Display lag is made of more than one wait, and the ones that are usually
    left out are the ones this exists to expose. Every ``*_at`` is a reading
    of the stream's clock, in seconds, monotonic and comparable only to each
    other. Every ``*_ms`` is audio time on the session clock.

    The stages, in order:

    ``ready_at``
        the segmenter released the segment. By then ``received_ms`` of this
        track's audio had been captured - already past ``end_ms``, because the
        cut decision waits for the lookback window.
    ``admitted_at``
        the segment took a place in the queue. It never blocks, so this is
        ``ready_at`` unless the queue was full, in which case it is ``None``
        and the segment was dropped.
    ``request_started_at``
        a concurrency slot came free and the request went out. The gap from
        ``admitted_at`` is time spent queued behind other requests.
    ``request_ended_at``
        the response came back, retries included.
    ``released_at``
        the utterance passed the ordering barrier and went to the consumer.
        The gap from ``request_ended_at`` is time spent waiting behind an
        *older* segment whose request had not finished - answering early buys
        a later segment nothing.

    What is deliberately absent is everything past this process. There is no
    browser receipt or render time here because this repository has no browser
    path yet, and a number that stopped at the edge of the process would be
    reported as if it were a reader's experience.
    """

    segment_index: int
    start_ms: int
    end_ms: int
    received_ms: int
    cut_reason: CutReason
    ready_at: float
    admitted_at: float | None = None
    request_started_at: float | None = None
    request_ended_at: float | None = None
    released_at: float | None = None
    utterance_id: str | None = None
    outcome: str = "PENDING"

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def decision_lag_ms(self) -> int:
        """Audio captured past this segment's end before the cut was decided.

        Non-zero for a forced cut, which is moved back into the lookback
        window: the segmenter heard up to ``received_ms`` before it could
        place the end at ``end_ms``. That audio was sitting captured and
        unsent for this long, and a measurement starting at ``end_ms`` misses
        it entirely.
        """

        return self.received_ms - self.end_ms

    @property
    def first_sample_wait_ms(self) -> int:
        """Audio captured between this segment's first sample and the cut.

        The segment's own duration plus :attr:`decision_lag_ms`. Under
        real-time capture it is how long the first sample had been sitting
        here before anything was sent anywhere.
        """

        return self.received_ms - self.start_ms

    @property
    def queue_wait_ms(self) -> int | None:
        """Time queued for a concurrency slot, once admitted."""

        return _elapsed_ms(self.admitted_at, self.request_started_at)

    @property
    def request_ms(self) -> int | None:
        """Time the transcription request took, retries included."""

        return _elapsed_ms(self.request_started_at, self.request_ended_at)

    @property
    def head_of_line_wait_ms(self) -> int | None:
        """Time held back by an older segment that had not answered yet."""

        return _elapsed_ms(self.request_ended_at, self.released_at)

    @property
    def pipeline_ms(self) -> int | None:
        """From the segmenter releasing the segment to the consumer getting it."""

        return _elapsed_ms(self.ready_at, self.released_at)

    @property
    def source_to_release_ms(self) -> int | None:
        """From this segment's first sample to its text reaching the consumer.

        **Assumes real-time capture** - that audio was pushed in as it was
        spoken, which is true of a live track and false of a file replayed at
        speed. Under that assumption the first sample was captured
        ``received_ms - start_ms`` before ``ready_at``, and this is the whole
        in-process wait for it.

        It is still not display lag. Whatever carries the utterance to a
        screen is not in this process and is not counted here.
        """

        pipeline = self.pipeline_ms
        if pipeline is None:
            return None
        return (self.received_ms - self.start_ms) + pipeline

    @property
    def speech_end_to_release_ms(self) -> int | None:
        """From this segment's last sample to its text reaching the consumer.

        The figure to hold against TechSpec N1 ("STT 결과가 표시되는 시간"):
        a reader waits from when the speaker stopped, not from when they
        started. It is :attr:`source_to_release_ms` less the segment's own
        duration, which leaves the cut decision, the queue, the request and
        the ordering barrier. Same real-time capture assumption, and the same
        missing hop to the screen.
        """

        pipeline = self.pipeline_ms
        if pipeline is None:
            return None
        return self.decision_lag_ms + pipeline

    @property
    def proxy_display_lag_ms(self) -> int | None:
        """Segment duration plus request time - the older, published figure.

        Kept so the two can be compared rather than confused. It is what the
        standalone benchmark harness reported as display lag, and it omits the
        cut decision, the queue and the ordering barrier, so it reads lower
        than :attr:`source_to_release_ms` by exactly the waits it skips.
        """

        request = self.request_ms
        if request is None:
            return None
        return self.duration_ms + request


def _elapsed_ms(start: float | None, end: float | None) -> int | None:
    if start is None or end is None:
        return None
    return round((end - start) * 1000)


@dataclasses.dataclass
class _Work:
    """One segment's place in the queue: its audio, its request, its clock.

    ``abandoned`` is the record that :meth:`TranscriptionStream.aclose` has
    already settled this item. Cancelling the task is not that record, because
    a task that has already finished cannot be cancelled: if the provider
    answers in the same loop iteration that abandons the stream, the cancel is
    a no-op and the waiting consumer is handed a perfectly good result for a
    segment the stream has stopped owning. The flag is what a consumer checks,
    so the decision is "was this item abandoned" rather than "did cancelling it
    happen to work".
    """

    segment: AudioSegment
    task: "asyncio.Task[Transcription]"
    timing: SegmentTiming
    abandoned: bool = False


def _retrieve_exception(task: "asyncio.Task[Transcription]") -> None:
    """Mark a finished request's failure as seen.

    A task nobody awaits - one abandoned when a consumer walks away or the
    stream is closed under it - is reported by asyncio at collection time as
    "Task exception was never retrieved", with the full traceback. That
    traceback is written by asyncio's own handler, not by this module's
    logger, and an ``httpx`` frame in it carries the deployment URL. Reading
    the exception here is what stops that from ever being printed.
    """

    if not task.cancelled():
        task.exception()


def _abandoned_under(task: "asyncio.Task[Transcription]") -> bool:
    """Whether a ``CancelledError`` came from the request, not the consumer.

    Awaiting a shielded task can be interrupted from either side, and the two
    mean opposite things: the request being cancelled is the stream ending,
    while the consumer being cancelled is the caller leaving and must be
    re-raised. The request is only the cause if it is the one that ended
    cancelled *and* nobody has asked this task to stop - a caller cancelling
    at the same moment as :meth:`TranscriptionStream.aclose` is still a
    cancellation of the caller, and swallowing it would make this task one
    that ignored being cancelled.
    """

    if not task.cancelled():
        return False
    current = asyncio.current_task()
    return current is None or current.cancelling() == 0


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
    iterate the instance to receive utterances in spoken order. The consumer
    may be running the whole time; it waits through gaps in the audio and ends
    when the closed stream runs out.

    ``ordering`` places this track on its session's timeline and is what makes
    ``seq`` comparable against another speaker's - see
    :mod:`irya_ai.stt.session`. A stream given none is treated as the only
    track in its session, which is right for a single track and wrong the
    moment there are two.

    ``clock`` is read for :attr:`timings` only and exists so a test can drive
    the stages without sleeping.

    One instance covers one track for one session, start to finish. It cannot
    be reused or resumed: the sample clock and the segment index start at zero
    and only move forward, so a second stream for the same track places its
    audio back at the beginning of the track and re-issues utterance ids from
    ``utt_<track>_0000``. Reconnect continuity is not implemented anywhere in
    this package - :mod:`irya_ai.stt.session` says what a caller who needs it
    is left holding.
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
        max_pending: int = DEFAULT_MAX_PENDING,
        ordering: TrackOrdering | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_pending < 1:
            raise ValueError("max_pending must be at least 1")
        # A zero here is the dangerous one: ``Semaphore(0)`` never grants a
        # slot, so every segment would sit in the queue forever and the
        # interview would look live while transcribing nothing.
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if not session_id:
            raise ValueError("session_id must not be empty")
        if not track_id:
            raise ValueError("track_id must not be empty")
        if ordering is not None and ordering.track_id != track_id:
            raise ValueError(f"ordering is for {ordering.track_id}, not {track_id}")

        self.client = client
        self.session_id = session_id
        self.track_id = track_id
        self.speaker = speaker
        self.segmenter = StreamSegmenter(config)
        self.ordering = ordering or solo_ordering(track_id)
        self.max_pending = max_pending
        self.rejected: list[RejectedSegment] = []
        self.timings: list[SegmentTiming] = []

        self._clock = clock
        self._limit = asyncio.Semaphore(max_concurrency)
        self._pending: deque[_Work] = deque()
        self._wake = asyncio.Event()
        self._closed = False
        self._advancing = False

    @property
    def pending(self) -> int:
        """Segments waiting for, or inside, a request."""

        return len(self._pending)

    @property
    def dropped_spans(self) -> list[RejectedSegment]:
        """Spans refused admission, i.e. audio no request was ever made for.

        Non-empty means the transcript has holes that are not the model's
        fault and that no retry will fill, so any analysis downstream of it is
        working from an incomplete record. That is a fact about this session,
        and it is reported here rather than repaired, because this layer holds
        no recording to repair it from.
        """

        return [r for r in self.rejected if r.reason == "OVERLOADED"]

    @property
    def overloaded(self) -> bool:
        """Whether audio has been dropped for want of a queue slot."""

        return any(r.reason == "OVERLOADED" for r in self.rejected)

    def push(self, pcm: bytes) -> int:
        """Feed audio in. Returns how many segments were *accepted*.

        Never blocks and never awaits: audio is live, and a producer made to
        wait on the network drops it somewhere less visible. A segment the
        queue has no room for is refused here and recorded in
        :attr:`dropped_spans`, so the return value can be lower than the
        number of segments the audio actually contained.
        """

        if self._closed:
            raise RuntimeError("cannot push into a closed stream")
        accepted = sum(self._schedule(s) for s in self.segmenter.push(pcm))
        self._wake.set()
        return accepted

    def close(self) -> int:
        """Stop accepting audio and send whatever is left in the buffer.

        The consumer keeps going until everything already queued has been
        resolved and released; this only says no more is coming.
        """

        if self._closed:
            return 0
        self._closed = True
        accepted = sum(self._schedule(s) for s in self.segmenter.flush())
        self._wake.set()
        return accepted

    async def aclose(self) -> None:
        """Abandon the stream: cancel what is in flight and release it.

        For the caller who is giving up rather than finishing - a session that
        ended early, a consumer that raised. Segments still queued produce no
        utterances and are recorded as abandoned, and every outstanding
        request is cancelled and collected so none is left to be reported by
        asyncio with a traceback.

        Abandonment is terminal and happens once. A request that had already
        come back - successfully or as an :class:`SttError` - is abandoned all
        the same: the cancel does nothing for it, but the flag still stops a
        consumer waiting on it from emitting the result or filing a second
        rejection for a segment this stream no longer owns.
        """

        self._closed = True
        abandoned, self._pending = self._pending, deque()
        for work in abandoned:
            work.abandoned = True
            work.task.cancel()
            if work.timing.outcome == "PENDING":
                work.timing.outcome = "ABANDONED"
        if abandoned:
            await asyncio.gather(
                *(work.task for work in abandoned), return_exceptions=True
            )
        self._wake.set()

    def _schedule(self, segment: AudioSegment) -> bool:
        now = self._clock()
        timing = SegmentTiming(
            segment_index=segment.index,
            start_ms=self.ordering.session_ms(segment.start_ms),
            end_ms=self.ordering.session_ms(segment.end_ms),
            received_ms=self.ordering.session_ms(segment.received_ms),
            cut_reason=segment.reason,
            ready_at=now,
        )
        self.timings.append(timing)

        if len(self._pending) >= self.max_pending:
            timing.released_at = now
            self._reject(segment, "OVERLOADED", timing)
            return False

        timing.admitted_at = now
        task = asyncio.ensure_future(self._transcribe(segment, timing))
        task.add_done_callback(_retrieve_exception)
        self._pending.append(_Work(segment=segment, task=task, timing=timing))
        return True

    async def _transcribe(
        self, segment: AudioSegment, timing: SegmentTiming
    ) -> Transcription:
        async with self._limit:
            timing.request_started_at = self._clock()
            try:
                audio = wav_bytes(segment.pcm, self.segmenter.config.sample_rate)
                return await self.client.transcribe(
                    audio, filename=f"seg_{segment.index:04d}.wav"
                )
            finally:
                timing.request_ended_at = self._clock()

    async def __aiter__(self) -> AsyncIterator[Utterance]:
        """Yield utterances in spoken order, waiting through gaps in the audio.

        Ends when the stream has been closed *and* everything queued has been
        released. An open stream with an empty queue waits for the next
        segment; ending there would silently hand the rest of the interview to
        whoever happened to start iterating next.

        A segment is taken off the queue once it has been resolved, so a
        consumer cancelled while waiting for a response leaves it in place for
        the next consumer, and one cancelled at the yield loses that single
        utterance rather than risking delivering it twice. Breaking out of the
        loop and starting a fresh one later is fine; what is refused is two
        consumers advancing the queue at once, which would split the order
        between them so that neither saw it whole.
        """

        while True:
            if self._pending:
                # The guard covers the resolve-then-pop step only. A consumer
                # parked at the ``yield`` below - one that has broken out of
                # its loop, say - holds nothing, because a generator's
                # ``finally`` does not run on ``break``; it waits for the
                # garbage collector, and a guard released there would stay
                # taken for an arbitrary time.
                if self._advancing:
                    raise RuntimeError(
                        "a transcription stream has one consumer at a time"
                    )
                self._advancing = True
                work = self._pending[0]
                try:
                    utterance = await self._resolve(work)
                    # By identity, because ``aclose`` can empty the queue
                    # while this is waiting: popping blind would take a
                    # segment that was never resolved, or raise on a deque
                    # that no longer holds anything.
                    if self._pending and self._pending[0] is work:
                        self._pending.popleft()
                finally:
                    self._advancing = False
                if utterance is not None:
                    yield utterance
                continue
            if self._closed:
                return
            # Clear before looking again, never after: a push landing
            # between the check and the clear would otherwise have its
            # wake-up erased, and the consumer would sleep through it.
            self._wake.clear()
            if self._pending or self._closed:
                continue
            await self._wake.wait()

    async def drain(self) -> list[Utterance]:
        """Every utterance of the track, once the track has ended.

        Waits for :meth:`close`, which means calling this on a stream that is
        never closed waits forever. It is the batch shape of iterating the
        stream, so it is for a caller that has all the audio already or is
        closing the stream from another task; a live consumer iterates.
        """

        return [utterance async for utterance in self]

    async def _resolve(self, work: _Work) -> Utterance | None:
        segment, timing = work.segment, work.timing
        try:
            # Shielded, because a task awaiting another task directly *is*
            # that task's waiter: cancelling the consumer would cancel the
            # request under it, and the segment left at the head of the queue
            # for the next consumer would be one that can never be resolved.
            # :meth:`aclose` still cancels these explicitly.
            transcription = await asyncio.shield(work.task)
        except asyncio.CancelledError:
            if not _abandoned_under(work.task):
                # This consumer is the one being cancelled. The request keeps
                # running behind the shield and the segment keeps its place,
                # so the next consumer picks it up where this one left it.
                raise
            # :meth:`aclose` cancelled the request under us. It has already
            # recorded the segment as abandoned, so there is nothing to log
            # and nothing to reject: returning ends the iteration on the
            # now-empty queue rather than raising into the caller's task.
            return None
        except SttError as exc:
            failure = exc
        else:
            failure = None

        # Both arms land here, because both can be reached after the stream
        # was abandoned. Cancelling a task that has already finished does
        # nothing, so a request that completed in the same iteration as
        # :meth:`aclose` resumes this consumer with a result or an error
        # rather than a ``CancelledError``. Neither may be used: the item is
        # off the queue, its outcome is already terminal, and emitting or
        # rejecting here would hand out an utterance the stream disowned or
        # file a second record against one segment.
        if work.abandoned:
            return None

        if failure is not None:
            # The code and the span, and nothing else. No ``exc_info``: the
            # traceback runs through ``httpx`` frames holding the deployment
            # URL, and no provider text, which is free-form and unvetted.
            logger.warning(
                "segment %d (%d-%dms, cut=%s) was not transcribed: %s",
                segment.index,
                timing.start_ms,
                timing.end_ms,
                segment.reason.value,
                failure.code,
            )
            return self._reject(segment, "REQUEST_FAILED", timing, code=failure.code)

        if transcription.is_empty:
            return self._reject(segment, "EMPTY", timing)
        if is_hallucinated(transcription, segment.duration_ms):
            # The model stamped the text over more time than it was given.
            # That does not establish what was or was not said, only that
            # the result describes audio this segment never carried, which
            # is enough to stop it from entering the transcript.
            return self._reject(segment, "TIMESTAMP_OVERRUN", timing)

        utterance = Utterance(
            utterance_id=f"utt_{self.track_id}_{segment.index:04d}",
            session_id=self.session_id,
            track_id=self.track_id,
            speaker=self.speaker,
            seq=self.ordering.seq(segment.start_ms),
            pass_type=PassType.FINAL,
            start_ms=timing.start_ms,
            end_ms=timing.end_ms,
            content=transcription.text,
        )
        timing.released_at = self._clock()
        timing.utterance_id = utterance.utterance_id
        timing.outcome = "RELEASED"
        return utterance

    def _reject(
        self,
        segment: AudioSegment,
        reason: str,
        timing: SegmentTiming,
        *,
        code: str | None = None,
    ) -> None:
        logger.info(
            "dropped segment %d (%dms, cut=%s): %s",
            segment.index,
            segment.duration_ms,
            segment.reason.value,
            reason,
        )
        if timing.released_at is None:
            timing.released_at = self._clock()
        timing.outcome = reason
        self.rejected.append(
            RejectedSegment(
                index=segment.index,
                start_ms=timing.start_ms,
                end_ms=timing.end_ms,
                cut_reason=segment.reason,
                reason=reason,
                code=code,
            )
        )
        return None
