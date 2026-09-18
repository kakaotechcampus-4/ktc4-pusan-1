"""Cartesia native streaming STT: provider events to utterances (#66).

:mod:`irya_ai.stt.stream` turns audio into utterances by cutting it into
segments and posting each one to Elice. This module turns audio into the same
utterances without cutting anything, because Cartesia does the cutting on the
far side of a WebSocket and tells us where it cut.

Why this is not a client swapped into ``TranscriptionStream``
-------------------------------------------------------------

``TranscriptionStream`` is almost entirely machinery for problems that
concurrent batch HTTP creates: a segmenter to decide where a request starts
and ends, ``max_concurrency`` to bound requests in flight, ``max_pending`` to
drop rather than grow without limit, an ordering barrier because request *N+1*
can answer before *N*, and ``asyncio.shield`` so a cancelled consumer does not
abandon a request that has already been paid for. A provider that emits one
FINAL at a time, in spoken order, over a connection it owns has none of those
problems. Reusing that class would mean disabling every part of it and keeping
only the ``Utterance`` construction at the end.

What the two paths genuinely share is the *output contract* - an async
iterator of :class:`~irya_ai.schemas.transcript.Utterance` carrying a
session-wide ``seq`` - so that is what is shared, and nothing else.
:class:`~irya_ai.stt.session.TrackOrdering` is used by both and is the reason
utterances from this path and utterances from the Elice path can be sorted
into one transcript.

The time origin
---------------

``SpeechData.start_time`` and ``end_time`` are seconds measured from the start
of *the provider stream*, not from the start of the track and not from the
start of the session. This module converts them to track-local milliseconds by
taking that equality at face value: **the caller must open the provider stream
at the moment the track's first audio frame is pushed.** A stream opened when
the room is joined but fed only once the participant unmutes puts every
utterance of that track early by the length of the gap, silently and without
any value in the data looking wrong.

The session offset is a separate question and is not this module's to answer:
``TrackOrdering.offset_ms`` carries it, the caller owns it, and
:mod:`irya_ai.stt.session` documents what a wrong one does.

Why the timing is trusted at all
--------------------------------

Only because ``ink-whisper`` reports ``aligned_transcript="word"``. A provider
that reports ``False`` - ``ink-2`` does - returns ``end_time = 0.0`` on every
alternative, and nothing about that is visibly broken: the text is still
there, the events still arrive, and every utterance simply claims to have been
spoken at time zero. Measurements taken against such a provider silently stop
meaning what they say. :data:`REASON_NO_TIMING` exists so that this fails
loudly here instead.

FINAL only, structurally
------------------------

``INTERIM_TRANSCRIPT`` events are counted and dropped. This is not an unset
flag. ``livekit-plugins-cartesia`` 1.8.0 resolves any ``ink-whisper`` model to
``"legacy"`` mode and therefore to ``interim_results=False``, and a non-English
language resolves to ``ink-whisper``, so a Korean interview produces no interim
events to begin with.

Passing them through if a future provider did emit them is a decision nobody
has made yet, and it is not free:
:meth:`~irya_ai.schemas.transcript.TranscriptSnapshot._check_revisions` pins
``(track_id, speaker, seq, start_ms)`` across every revision of one utterance
id, so an INTERIM would have to commit to the start time - and hence the ``seq``
- that the eventual FINAL turns out to have. Providers revise span boundaries
between interim and final results. Emitting INTERIM safely means pinning the
first interim's start for the whole utterance and accepting that the FINAL's
own start is discarded; that is a real trade and it should be made on purpose.

What is deliberately absent
---------------------------

- **No hallucination guard.** :func:`~irya_ai.stt.elice.is_hallucinated` asks
  whether a transcript describes more audio than the segment that was sent.
  Here there is no segment: the provider chose the span, so there is no
  independent bound to check it against, and ``TIMESTAMP_OVERRUN`` has no
  analogue. A Cartesia utterance claiming an implausible duration would pass.
- **No retries and no fallback.** A dropped WebSocket ends the iteration. The
  reconnect story is the caller's, and :mod:`irya_ai.stt.session` explains why
  a reconnected track cannot simply resume this one's numbering. Elice is a
  batch API with no streaming route at all, so it is not a live fallback for
  this path - only a re-transcription pass over a recording.
- **No audio.** Nothing here holds PCM, so nothing here needs a retention
  policy. Rejections keep a span and a reason, as in
  :class:`~irya_ai.stt.stream.RejectedSegment`.
- **No ``protect_host``.** The Elice client redacts its host from ``httpx``
  logs because the base URL identifies a private deployment. Cartesia's
  endpoint is the provider's public one and identifies nothing.
"""

import dataclasses
import logging
import time
from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import TYPE_CHECKING

from livekit.agents import stt as livekit_stt
from livekit.agents.types import NOT_GIVEN, NotGivenOr

from irya_ai.config import Settings, get_settings
from irya_ai.schemas.transcript import PassType, SpeakerRole, Utterance, Word
from irya_ai.stt.session import TrackOrdering, solo_ordering

if TYPE_CHECKING:
    from livekit.plugins import cartesia as cartesia_plugin

logger = logging.getLogger(__name__)

# The only Cartesia model this path is meant for. ``ink-2`` is English-only:
# the plugin warns on construction, and Korean comes back as English syllables
# ("Ndapshigan Piguushibonin ..."), which is not a degraded transcript but an
# unusable one.
DEFAULT_MODEL = "ink-whisper"
DEFAULT_LANGUAGE = "ko"

# The rate the rest of the STT layer already speaks in; see ``tests/audio.py``
# and the segmenter. Resampling belongs to whoever captures the track.
SAMPLE_RATE = 16000

# Why an event produced no utterance. ``EMPTY`` is spelled as in
# :class:`~irya_ai.stt.stream.RejectedSegment` so that the two paths' rejection
# records can be read together; the rest have no batch counterpart.
REASON_EMPTY = "EMPTY"
REASON_NO_TIMING = "NO_TIMING"
REASON_TIMESTAMP_INVALID = "TIMESTAMP_INVALID"
REASON_OUT_OF_ORDER = "OUT_OF_ORDER"


@dataclasses.dataclass(frozen=True)
class RejectedEvent:
    """Why one FINAL event produced no utterance.

    Holds no provider text. The text of a rejected event is free-form, unvetted
    and - for :data:`REASON_NO_TIMING` - exactly the thing that looked fine and
    was not, so a record of it invites someone to use it anyway. The event's
    place in the stream and the reason are what explain a gap afterwards.
    """

    index: int
    start_ms: int
    end_ms: int
    reason: str


@dataclasses.dataclass
class EventTiming:
    """When one accepted utterance was spoken and when it reached us.

    ``lag_ms`` is the number this path exists to make small: the wall-clock gap
    between the end of the audio, as the provider timed it, and the moment the
    consumer could have displayed it. It is comparable to the Elice path's
    ``request_ended_at - ready_at`` only in spirit - that one is bounded by a
    segmenter waiting for 700ms of silence before it even starts a request.

    It stops at the edge of this process. The LiveKit text-stream bridge now
    delivers the result to the browser, but receipt and render time are not
    measured here; a number that stopped here must not be reported as a
    reader's experience.
    """

    index: int
    utterance_id: str
    start_ms: int
    end_ms: int
    received_at: float
    lag_ms: int


def _milliseconds(seconds: float) -> int:
    return round(seconds * 1000)


def _given(value: NotGivenOr[float]) -> float | None:
    """A LiveKit optional float as a plain one.

    ``NotGivenOr`` distinguishes "the provider did not say" from "the provider
    said zero", and the two mean different things for a timestamp.
    """

    return None if value is NOT_GIVEN else float(value)


class CartesiaTranscriptionStream:
    """Turns one track's Cartesia speech events into utterances.

    The constructor takes no provider and no connection. It is fed an async
    iterable of :class:`~livekit.agents.stt.SpeechEvent`, which is what
    ``cartesia.STT(...).stream()`` yields, so the conversion can be tested
    against events built by hand rather than against a WebSocket::

        stream = CartesiaTranscriptionStream(
            session_id="ses_123",
            track_id="trk_candidate",
            speaker=SpeakerRole.CANDIDATE,
            ordering=session_ordering.register("trk_candidate"),
        )
        async for utterance in stream.utterances(provider_stream):
            ...

    One instance per track per provider stream. It keeps the utterance index
    and the last accepted start, and neither survives a reconnect - see
    "Lifetime" in :mod:`irya_ai.stt.session`.
    """

    def __init__(
        self,
        *,
        session_id: str,
        track_id: str,
        speaker: SpeakerRole,
        ordering: TrackOrdering | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ordering is not None and ordering.track_id != track_id:
            raise ValueError(f"ordering is for {ordering.track_id}, not {track_id}")

        self.session_id = session_id
        self.track_id = track_id
        self.speaker = speaker
        self.ordering = ordering or solo_ordering(track_id)
        self._clock = clock

        self.timings: list[EventTiming] = []
        self.rejected: list[RejectedEvent] = []
        self.interim_seen = 0

        self._index = 0
        self._last_start_ms: int | None = None
        self._started_at: float | None = None

    def start(self) -> None:
        """Pin the provider stream's wall-clock origin.

        The LiveKit bridge calls this immediately before it pushes the first
        audio frame. Direct consumers do not have to call it: ``utterances``
        falls back to pinning the origin when iteration begins. Keeping the
        operation idempotent makes it safe for the bridge to start the clock
        before the receive task begins without that task moving it again.
        """

        if self._started_at is None:
            self._started_at = self._clock()

    async def utterances(
        self, events: AsyncIterable[livekit_stt.SpeechEvent]
    ) -> AsyncIterator[Utterance]:
        """Yield an utterance per accepted FINAL, in the order they arrive.

        Arrival order is spoken order here - the provider emits one FINAL at a
        time for a span it has already closed - so unlike the Elice path there
        is no barrier holding a finished result back to wait for an older one.

        Iterating starts this track's clock unless :meth:`start` already pinned
        it. The LiveKit bridge uses the explicit form so the origin is the
        first pushed audio frame rather than task scheduling a little before
        or after it. Both the ``lag_ms`` readings and the provider's own
        timestamps are measured from that instant.
        """

        self.start()
        async for event in events:
            if event.type is livekit_stt.SpeechEventType.INTERIM_TRANSCRIPT:
                self.interim_seen += 1
                continue
            if event.type is not livekit_stt.SpeechEventType.FINAL_TRANSCRIPT:
                continue

            utterance = self._accept(event)
            if utterance is not None:
                yield utterance

    def _accept(self, event: livekit_stt.SpeechEvent) -> Utterance | None:
        """Validate one FINAL and turn it into an utterance, or record why not."""

        alternative = event.alternatives[0] if event.alternatives else None
        if alternative is None:
            return self._reject(0, 0, REASON_EMPTY)

        content = alternative.text.strip()
        start_ms = _milliseconds(alternative.start_time)
        end_ms = _milliseconds(alternative.end_time)

        # ``content`` is required to be non-empty by the schema, so an empty
        # FINAL is not a degenerate utterance - it is a ValidationError raised
        # inside whatever task is draining this stream. Cartesia does send
        # them: the ink-2 fast_speech run produced a FINAL with no body.
        if not content:
            return self._reject(start_ms, end_ms, REASON_EMPTY)

        # Text with no span. A provider whose ``aligned_transcript`` is False
        # reports every alternative as 0.0 to 0.0; see the module docstring.
        if end_ms <= 0:
            return self._reject(start_ms, end_ms, REASON_NO_TIMING)

        # ``Utterance`` enforces this too, but as an exception in the consumer.
        if end_ms < start_ms or start_ms < 0:
            return self._reject(
                max(start_ms, 0), max(end_ms, 0), REASON_TIMESTAMP_INVALID
            )

        # ``seq`` is built from ``start_ms``, so a start that moves backwards
        # would place this utterance before one already released. Note that
        # equal starts are accepted: ``seq`` then collides, and the tie breaks
        # on the zero-padded utterance id, which for one track is issue order
        # and therefore still spoken order.
        if self._last_start_ms is not None and start_ms < self._last_start_ms:
            return self._reject(start_ms, end_ms, REASON_OUT_OF_ORDER)

        index = self._index
        self._index += 1
        self._last_start_ms = start_ms

        utterance = Utterance(
            utterance_id=f"utt_{self.track_id}_{index:04d}",
            session_id=self.session_id,
            track_id=self.track_id,
            speaker=self.speaker,
            seq=self.ordering.seq(start_ms),
            pass_type=PassType.FINAL,
            start_ms=self.ordering.session_ms(start_ms),
            end_ms=self.ordering.session_ms(end_ms),
            content=content,
            words=self._words(alternative, start_ms, end_ms),
        )

        # ``event.created_at`` is a wall-clock reading, on no origin this track
        # shares, so the arrival time is taken from the stream's own clock -
        # the one started by :meth:`utterances`, which is the provider's origin
        # too. ``end_ms`` is subtracted before the session offset is applied,
        # because a lag is a duration and must not be moved by it.
        started_at = self._started_at if self._started_at is not None else self._clock()
        received_at = self._clock()
        self.timings.append(
            EventTiming(
                index=index,
                utterance_id=utterance.utterance_id,
                start_ms=utterance.start_ms,
                end_ms=utterance.end_ms,
                received_at=received_at,
                lag_ms=_milliseconds(received_at - started_at) - end_ms,
            )
        )
        return utterance

    def _words(
        self, alternative: livekit_stt.SpeechData, start_ms: int, end_ms: int
    ) -> list[Word]:
        """Word timings, for the words that actually carry them.

        ``ink-whisper`` is the model chosen partly *because* it aligns words,
        but alignment is per word and the provider may omit it for any of them.
        A word without a usable span is dropped rather than given the
        utterance's own span, which would read as timing rather than as absent
        timing. A partial list is allowed: the schema defaults ``words`` to
        empty and no consumer requires it to cover the text.
        """

        if not alternative.words:
            return []

        words: list[Word] = []
        for word in alternative.words:
            content = str(word).strip()
            if not content:
                continue

            offset = _given(getattr(word, "start_time_offset", NOT_GIVEN)) or 0.0
            word_start = _given(getattr(word, "start_time", NOT_GIVEN))
            word_end = _given(getattr(word, "end_time", NOT_GIVEN))
            if word_start is None or word_end is None:
                continue

            word_start_ms = _milliseconds(word_start + offset)
            word_end_ms = _milliseconds(word_end + offset)
            if word_end_ms < word_start_ms or word_start_ms < 0:
                continue
            if word_start_ms < start_ms or word_end_ms > end_ms:
                # Outside the utterance it belongs to. Whatever origin this
                # word is on, it is not the one the utterance is on, and
                # placing it anyway would put a word in a neighbour's span.
                continue

            confidence = _given(getattr(word, "confidence", NOT_GIVEN))
            words.append(
                Word(
                    seq=len(words),
                    start_ms=self.ordering.session_ms(word_start_ms),
                    end_ms=self.ordering.session_ms(word_end_ms),
                    content=content,
                    confidence=(
                        confidence
                        if confidence is not None and 0.0 <= confidence <= 1.0
                        else None
                    ),
                )
            )
        return words

    def _reject(self, start_ms: int, end_ms: int, reason: str) -> None:
        """Record a dropped event and return nothing, so the caller yields nothing."""

        index = len(self.rejected)
        self.rejected.append(
            RejectedEvent(index=index, start_ms=start_ms, end_ms=end_ms, reason=reason)
        )
        # The reason and the span, and nothing else. No provider text: it is
        # free-form and unvetted, and the interview it came from is somebody's.
        logger.warning(
            "cartesia event rejected: reason=%s track=%s span=%d-%dms",
            reason,
            self.track_id,
            start_ms,
            end_ms,
        )
        return None


def build_stt(
    settings: Settings | None = None, *, sample_rate: int = SAMPLE_RATE
) -> "cartesia_plugin.STT":
    """The configured Cartesia provider, ready to ``.stream()``.

    Kept apart from :class:`CartesiaTranscriptionStream` on purpose: this is
    the half that needs a key and a network, and that class is the half worth
    testing. The plugin is imported here rather than at module scope for the
    same reason - the conversion can be exercised without the provider package
    resolving its own transitive dependencies.

    The model is not passed through blindly. ``ink-whisper`` is what the
    latency and accuracy measurements in ``stt-bench`` were taken against, and
    the plugin silently changes mode - and language support - for anything
    else, so a different value is refused rather than quietly run.
    """

    from livekit.plugins import cartesia as cartesia_plugin

    settings = settings or get_settings()
    if settings.cartesia_stt_model != DEFAULT_MODEL:
        raise ValueError(
            f"only {DEFAULT_MODEL} is supported here, "
            f"not {settings.cartesia_stt_model!r}; see the module docstring"
        )

    key = settings.cartesia_api_key.get_secret_value()
    if not key:
        raise ValueError("CARTESIA_API_KEY is not set")

    return cartesia_plugin.STT(
        model=settings.cartesia_stt_model,
        language=settings.cartesia_stt_language,
        sample_rate=sample_rate,
        api_key=key,
    )
