"""Stage-demo utterance injection: a scripted answer entering the real pipeline.

Why this exists
---------------

The final presentation has to show the two things the product is judged on -
live captions and follow-up questions - from a stage, in about two minutes,
with one person. The interviewer is real: they speak into a microphone and
their words go through the real STT. The candidate cannot be: there is nobody
in the other chair.

So exactly one thing is replaced, and it is as small as it can be: **the sound
the candidate would have made.** The scripted answer is handed to the pipeline
as a FINAL candidate utterance, at the point where STT would have released it,
and from there nothing is special-cased. The utterance travels the production
path - :class:`~irya_ai.stt.rtc_bridge.LiveKitTextSink` puts it on the
interviewer's caption, :mod:`irya_ai.transcript_runner` stores it, and
:mod:`irya_ai.suggestion_runner` pairs it with the question that was *actually
spoken* and runs the real generator over it, grounding checks included. A
follow-up whose quote is not a verbatim substring of the scripted answer is
dropped here exactly as it would be in an interview.

That is the honest claim the presenter can make: the captions and the
follow-up questions are generated, not played back. Only the voice is missing.

Which rooms this can happen in
------------------------------

**One named session at a time, never "every room on this host".**
:func:`attach_demo_injector` attaches only when ``DEMO_INJECTION_ENABLED`` is
on *and* the room's session id is listed in ``DEMO_INJECTION_SESSIONS``. An
empty list attaches nothing, so turning the flag on without naming a session
is not a way to open every interview. Every other room gets no handler at all
and never even parses a demo packet.

This is the control that matters. A deployment-wide boolean would mean that
while the demo is armed, any interviewer on the same host could put scripted
speech into a real candidate's transcript by pressing one key, with nothing on
screen to say so.

How it is triggered
-------------------

Not from the browser. Interviewer and candidate tokens are issued with
``can_publish_data=False`` (``backend/app/services/media.py``), so no human in
the room can put a packet on the wire at all - **that** is what closes this
path today. The trigger is a backend endpoint that calls LiveKit's RoomService
``SendData``.

:meth:`DemoInjector.on_data` additionally requires ``participant is None``.
Be precise about what that buys: the SDK fills ``participant`` by looking the
sender's identity up in the room's participant map, so ``None`` means "no
participant in this room sent it" - true for a server packet, and also true
for a sender who has since left. It is a cheap sanity check that a human in
the room did not author the packet, not an authenticator. There is no secret
on the packet; the session allowlist above and the token grants are the real
boundary.

Placing the utterance on the timeline
-------------------------------------

``seq`` is what Q&A segmentation reads to decide which question an answer
belongs to (see :mod:`irya_ai.stt.session`), so it has to be right or the
pairing breaks quietly. The injected answer registers one track in the
session's :class:`~irya_ai.stt.session.SessionOrdering` and is placed at the
session millisecond it arrives, so it sorts after the question just asked.

Two injections in the same millisecond would otherwise land on the same
``seq`` with different ids, which breaks the uniqueness ``seq`` promises, so
:meth:`DemoInjector.inject` keeps its own strictly increasing clock: an answer
placed no later than the previous one is moved one millisecond past it. The
utterance id is derived from that placement rather than from a counter, so a
restarted worker - which re-creates the injector - does not re-issue an id
from the top. That holds only while the origin holds: ``initialize_origin``
pins t=0 to the earliest human join *currently present*, so a restart plus a
rejoin moves the origin later, the same wall-clock instant maps to a smaller
session millisecond, and a stored id can come round again. Good enough for a
demo, and worth knowing before reusing this anywhere else.

Two orderings are assumed rather than enforced, and both are what the stage
script does anyway. The demo track registers on first use, and a real
microphone track registers on its first audio *frame*
(:mod:`irya_ai.stt.rtc_bridge`), so pressing the key before speaking - or
while still muted, or inside the join-to-first-frame window - gives the demo
track the earlier ordinal. That only matters for a question and an answer
landing on the same millisecond, which is why it is left as an assumption:
**speak first, then press.**

``end_ms`` is estimated from the text at :data:`SPEAKING_CHARS_PER_SECOND`.
Nothing downstream decides anything from it - the answer's word count comes
from the content - but a span of zero would be a lie about speech that takes
seconds to say.
"""

import asyncio
import json
import logging

from livekit import rtc

from irya_ai.schemas.transcript import PassType, SpeakerRole, Utterance
from irya_ai.sinks import UtteranceSink
from irya_ai.stt.rtc_bridge import RoomTranscriber
from irya_ai.stt.session import TrackOrdering

logger = logging.getLogger(__name__)

#: The topic the backend sends on. Distinct from ``irya.transcript.v1`` (the
#: caption stream) and ``irya.suggestion.v1`` (follow-ups to the interviewer)
#: so that nothing already listening can mistake one for the other.
DEMO_TOPIC = "irya.demo.v1"

#: The injected answer's track. Named like a real one because that is what it
#: is as far as every consumer is concerned, and ``demo`` so that a stored
#: transcript - and every utterance id derived from it - says plainly where it
#: came from. Real tracks carry a LiveKit ``TR_…`` SID, so this cannot collide.
DEMO_TRACK_ID = "trk_demo_candidate"

#: Korean interview speech, roughly. Only used to give the utterance a
#: plausible duration; see the module docstring.
SPEAKING_CHARS_PER_SECOND = 5.5

#: Longer than any answer a presenter will read aloud on stage. A packet over
#: this is a mistake or an abuse, not a script.
MAX_CONTENT_CHARS = 2_000

#: How long :meth:`DemoInjector.aclose` waits on injections in flight. Short
#: on purpose: it runs on the job's shutdown path, which LiveKit gathers with
#: no timeout of its own, and by then the consumers are gone anyway.
CLOSE_TIMEOUT_SECONDS = 2.0


#: Characters stripped off each session id before matching. The browser side
#: of the demo takes a JSON array (``["ses_abc"]``) while the server env takes
#: a bare comma list, and the two get pasted into each other - a mistake that
#: would otherwise fail closed *silently*, as one literal id matching nothing.
#: Session ids never contain any of these, so accepting both shapes costs
#: nothing. Backend's ``Settings.demo_injection_session_ids`` must stay
#: identical to this.
_SESSION_ID_TRIM = "[]\"' \t\r\n"


def allowed_sessions(raw: str) -> frozenset[str]:
    """The session ids named in ``DEMO_INJECTION_SESSIONS``.

    Comma separated; surrounding brackets, quotes and blanks are ignored, so
    both ``ses_a,ses_b`` and ``["ses_a","ses_b"]`` read the same. An empty or
    blank setting gives an empty set, which allows nothing: the feature fails
    closed, so forgetting to name the demo session cannot open every room on
    the host. Matching is exact string equality - there is no wildcard, and a
    literal like ``*`` is just a session id that nothing is named.
    """

    parts = (part.strip(_SESSION_ID_TRIM) for part in raw.split(","))
    return frozenset(part for part in parts if part)


def parse_packet(payload: bytes) -> str | None:
    """The answer text in a demo packet, or ``None`` if it is not one.

    Shape: ``{"type": "demo.utterance", "content": "..."}``. Anything else -
    not JSON, not an object, wrong type, missing or blank content, too long -
    returns ``None``. The packet comes off the network, so this function
    refuses rather than raises: a malformed packet must not end the job.
    """

    try:
        message = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(message, dict):
        return None
    if message.get("type") != "demo.utterance":
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    content = content.strip()
    if not content or len(content) > MAX_CONTENT_CHARS:
        return None
    return content


def estimated_duration_ms(content: str) -> int:
    """How long saying *content* aloud would plausibly take, at least 1ms."""

    seconds = len(content) / SPEAKING_CHARS_PER_SECOND
    return max(1, round(seconds * 1000))


class DemoInjector:
    """Turns scripted answers into FINAL candidate utterances for one room.

    Holds the demo track's :class:`~irya_ai.stt.session.TrackOrdering` and the
    last millisecond it placed an answer at, so successive injections are
    ordered and carry distinct ids. One instance is one room.

    ``sink`` is where a built utterance goes - in the worker, the room's
    :class:`~irya_ai.sinks.FanOutSink`, which is also what isolates a failing
    consumer from this path.
    """

    def __init__(
        self,
        transcriber: RoomTranscriber,
        *,
        sink: UtteranceSink,
        track_id: str = DEMO_TRACK_ID,
    ) -> None:
        self._transcriber = transcriber
        self._sink = sink
        self._track_id = track_id
        self._ordering: TrackOrdering | None = None
        #: The last millisecond an answer was placed at, so the next one is
        #: strictly later. ``None`` until the first injection.
        self._last_ms: int | None = None
        #: Injections in flight. A set rather than one slot: two presses in
        #: quick succession would otherwise drop the reference the earlier
        #: task is being held by, which is the whole reason to keep it.
        self._pending: set[asyncio.Task[None]] = set()
        #: Utterances injected, and packets refused, for the end-of-job log.
        self.injected = 0
        self.refused = 0

    @property
    def session_id(self) -> str:
        return self._transcriber.session_id

    @property
    def in_flight(self) -> int:
        return len(self._pending)

    def _register(self) -> TrackOrdering:
        """The demo track's ordering, registered on first use.

        Registered at offset 0 and asked for ``seq`` with the session
        millisecond: the product is the same either way, and a fixed offset
        keeps :meth:`~irya_ai.stt.session.SessionOrdering.register` idempotent
        for the life of the room.
        """

        if self._ordering is None:
            self._ordering = self._transcriber.ordering.register(
                self._track_id, offset_ms=0
            )
        return self._ordering

    def _place(self, at_ms: int) -> int:
        """*at_ms*, or one past the last placement when that is not later.

        Keeps ``seq`` unique across injections. Two presses inside the same
        millisecond are the realistic case; a clock that went backwards is
        handled by the same rule.
        """

        if self._last_ms is not None and at_ms <= self._last_ms:
            at_ms = self._last_ms + 1
        self._last_ms = at_ms
        return at_ms

    def build(self, content: str, *, at_ms: int) -> Utterance:
        """One FINAL candidate utterance for *content*, spoken at *at_ms*.

        *at_ms* is taken as given; :meth:`inject` is what keeps the clock
        strictly increasing. The id is derived from the placement so that a
        restarted worker does not re-issue an id the Backend already stored.
        """

        ordering = self._register()
        return Utterance(
            utterance_id=f"utt_{self._track_id}_{at_ms:08d}",
            session_id=self.session_id,
            track_id=self._track_id,
            speaker=SpeakerRole.CANDIDATE,
            seq=ordering.seq(at_ms),
            pass_type=PassType.FINAL,
            start_ms=at_ms,
            end_ms=at_ms + estimated_duration_ms(content),
            content=content,
        )

    async def inject(self, content: str) -> Utterance | None:
        """Place *content* on the session timeline now and hand it to the sink.

        ``None`` when the room has no timeline yet: live-caption t=0 is pinned
        to the first human join, and before that there is no millisecond to
        place an utterance at. On stage this cannot happen - the presenter is
        already in the room - so it is logged and dropped rather than queued.
        """

        now_ms = self._transcriber.session_ms_now()
        if now_ms is None:
            self.refused += 1
            logger.warning(
                "demo injection before the session timeline exists; dropped session=%s",
                self.session_id,
            )
            return None
        utterance = self.build(content, at_ms=self._place(now_ms))
        await self._sink(utterance)
        self.injected += 1
        # The id and the span, never the text: an injected answer is still
        # interview speech, and that does not belong in an application log.
        logger.info(
            "demo utterance injected session=%s utterance=%s %d-%dms chars=%d",
            self.session_id,
            utterance.utterance_id,
            utterance.start_ms,
            utterance.end_ms,
            len(utterance.content),
        )
        return utterance

    def on_data(self, packet: rtc.DataPacket) -> None:
        """Room ``data_received`` handler. Refuses anything a human in the room sent.

        Synchronous because the event emitter is, so the work goes on a task.
        Every refusal path is silent to the sender by design - there is no
        reply channel - and logged here instead.
        """

        if packet.topic != DEMO_TOPIC:
            return
        if packet.participant is not None:
            # A participant in this room authored the packet. Human tokens are
            # issued without ``can_publish_data``, so this should be
            # unreachable; if it happens, the grants are wrong and the right
            # answer is to refuse and say so, not to serve it.
            self.refused += 1
            logger.warning(
                "demo packet from participant=%s refused session=%s",
                packet.participant.identity,
                self.session_id,
            )
            return
        content = parse_packet(packet.data)
        if content is None:
            self.refused += 1
            logger.warning(
                "malformed demo packet refused session=%s bytes=%d",
                self.session_id,
                len(packet.data),
            )
            return
        task = asyncio.create_task(
            self._inject_safely(content), name=f"demo-inject-{self.session_id}"
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _inject_safely(self, content: str) -> None:
        try:
            await self.inject(content)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a demo must never end the room
            logger.exception("demo injection failed session=%s", self.session_id)

    async def aclose(self, *, timeout: float = CLOSE_TIMEOUT_SECONDS) -> None:
        """Stop holding injections in flight, then report what this room did.

        Registered as a worker shutdown callback, and deliberately modest
        about what that can achieve. **An injection still in flight here has
        most likely already lost its consumers**, because the LiveKit job
        runner disconnects the room and then runs every shutdown callback
        *concurrently*: the transcript runner's ``stop`` sets its closed flag
        with no preceding await, so it wins that race and drops the utterance,
        and the caption's ``send_text`` has no room to send on. So this is not
        "the answer still reaches the Backend" - that would need an ordering
        shutdown callbacks cannot express. It is only: do not leave a task
        dangling, and get the counters into the log.

        Bounded, because the gather is on the job's shutdown path. LiveKit
        gathers the callbacks with no timeout of its own, so a send that hangs
        here would hang the whole job; the tasks are left to be cancelled with
        the job's other pending work instead.
        """

        if self._pending:
            done, pending = await asyncio.wait(tuple(self._pending), timeout=timeout)
            for task in done:
                if (exc := task.exception()) is not None and not isinstance(
                    exc, asyncio.CancelledError
                ):
                    logger.warning(
                        "demo injection ended in %s session=%s",
                        type(exc).__name__,
                        self.session_id,
                    )
            if pending:
                logger.warning(
                    "demo injection did not settle in %.1fs session=%s pending=%d",
                    timeout,
                    self.session_id,
                    len(pending),
                )
        logger.info(
            "demo injection closed session=%s injected=%d refused=%d",
            self.session_id,
            self.injected,
            self.refused,
        )


def attach_demo_injector(
    room: rtc.Room,
    transcriber: RoomTranscriber,
    *,
    enabled: bool,
    sessions: frozenset[str] | None = None,
    sink: UtteranceSink | None = None,
) -> DemoInjector | None:
    """Register the demo handler on *room*, or do nothing.

    Attaches only when ``enabled`` and this room's session is in *sessions*.
    Returns ``None`` otherwise - no handler, so a demo packet arriving at any
    other room is not even parsed. ``sessions`` left out means none, which is
    why the flag alone cannot open every interview on the host.
    """

    if not enabled:
        return None
    allowed = sessions or frozenset()
    if transcriber.session_id not in allowed:
        if allowed:
            logger.info(
                "demo injection is on but session=%s is not listed; no handler",
                transcriber.session_id,
            )
        else:
            logger.warning(
                "DEMO_INJECTION_ENABLED is on but DEMO_INJECTION_SESSIONS is "
                "empty; no room can be injected into"
            )
        return None
    if sink is None:
        sink = _first_sink(transcriber)
    injector = DemoInjector(transcriber, sink=sink)
    room.on("data_received", injector.on_data)
    logger.warning(
        "demo utterance injection is ENABLED for session=%s topic=%s",
        transcriber.session_id,
        DEMO_TOPIC,
    )
    return injector


def _first_sink(transcriber: RoomTranscriber) -> UtteranceSink:
    """The room's fan-out, which is what the worker puts in ``sinks``.

    Taken by reference rather than copied: the worker replaces ``sinks``
    after building the consumers, and an injector holding the earlier list
    would publish captions and nothing else.
    """

    if not transcriber.sinks:
        raise ValueError("the transcriber has no sink to inject into")

    async def fan_out(utterance: Utterance) -> None:
        for sink in transcriber.sinks:
            await sink(utterance)

    return fan_out
