"""Utterance sinks: where a live transcript goes once the STT path releases it.

The LiveKit worker (:mod:`irya_ai.stt.rtc_bridge`) hands every released
:class:`~irya_ai.schemas.transcript.Utterance` to a sequence of sinks, one
after the other. That sequence is the wiring point for everything downstream
of transcription - the interviewer's caption, the follow-up question agent,
the Backend transcript channel - and the one rule they share is that none of
them may take the interview down with it (TechSpec N4).

:class:`FanOutSink` is that rule. A sink that raises is logged and skipped
for this utterance; the others still receive it, and the next utterance is
offered to the failed sink again. It is deliberately the *only* place that
swallows a sink's exception: the bridge itself treats a raising sink as the
end of the track, so a sink that must not do that goes through here.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence

from irya_ai.schemas.transcript import Utterance

logger = logging.getLogger(__name__)

UtteranceSink = Callable[[Utterance], Awaitable[None]]


def sink_name(sink: UtteranceSink) -> str:
    """A stable label for logs: the function's name, or the callable's type."""

    return getattr(sink, "__name__", None) or type(sink).__name__


class FanOutSink:
    """Offer each utterance to every sink, in order, isolating their failures.

    Sinks run one after the other rather than concurrently so that every
    consumer sees utterances in release order, which the Backend transcript
    channel and the Q&A segmenter both depend on. Anything that awaits a
    model or a remote service therefore belongs *behind* a sink - in a queue
    drained by its own task - not inside one; a sink here should return in
    the time it takes to hand the utterance on.

    Cancellation is not a failure and passes straight through: the bridge
    cancels the receiver when the track ends, and the fan-out must stop with
    it rather than log the stop as an error.
    """

    def __init__(self, sinks: Sequence[UtteranceSink]) -> None:
        self.sinks: list[UtteranceSink] = list(sinks)
        #: How many utterances each sink has failed on, by :func:`sink_name`.
        #: Read by the end-of-track log; the first failure gets a traceback,
        #: later ones a one-line warning so a broken sink cannot flood the log.
        self.failures: Counter[str] = Counter()

    async def __call__(self, utterance: Utterance) -> None:
        for sink in self.sinks:
            try:
                await sink(utterance)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - isolation is the point of this class
                name = sink_name(sink)
                self.failures[name] += 1
                # The id and the span, never the text: a sink's failure is an
                # application event, and interview speech does not belong in
                # an application log.
                if self.failures[name] == 1:
                    logger.exception(
                        "sink %s failed utterance=%s %d-%dms; other sinks continue",
                        name,
                        utterance.utterance_id,
                        utterance.start_ms,
                        utterance.end_ms,
                    )
                else:
                    logger.warning(
                        "sink %s failed again (n=%d) utterance=%s",
                        name,
                        self.failures[name],
                        utterance.utterance_id,
                    )
