"""A circuit breaker for one STT deployment.

Without one, a deployment that has stopped answering is discovered again by
every segment. A rejected key fails each segment on its own; a run of 5xx
costs each segment its full retry budget; and a deployment that accepts the
connection and never answers - the outage actually seen during this work -
holds every segment for the stream's whole request deadline, in spoken
order, so captions stall behind it for as long as it lasts.

The breaker turns that into one discovery. After ``failure_threshold``
consecutive failed calls (or one rejected key) it opens, and calls fail at
once with ``STT_CIRCUIT_OPEN`` without sending anything. Every
``cooldown_seconds`` one call is let through as a probe; its success closes
the breaker and the next segment goes out as normal.

What it costs: a segment that arrives while the breaker is open is dropped,
and live audio cannot be sent again. A deployment that recovers just after
opening loses up to ``cooldown_seconds`` of speech it might have answered.
The cooldown is kept short for that reason. A call that fails while the
breaker is still closed is not affected - that cost was already being paid.

Admission and bookkeeping never ``await``, so on one event loop the
check-and-set of the probe is atomic: of many calls arriving at once while
the breaker is due a probe, exactly one is let through.
"""

import enum
import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 5.0


class Admission(enum.Enum):
    """What :meth:`CircuitBreaker.admit` decided for one call."""

    # Closed: send, with the client's normal retries.
    SEND = "SEND"
    # Open and due: send once, as the probe that decides whether to close.
    PROBE = "PROBE"
    # Open, or a probe is already out: fail without sending.
    REFUSE = "REFUSE"


class CircuitBreaker:
    """Consecutive-failure breaker with a single-flight half-open probe.

    ``on_state_change`` is called with ``True`` when the breaker opens and
    ``False`` when it closes, once per transition. It is for telling the
    room the transcript has gone quiet for a reason; an exception from it is
    logged and swallowed, because a broken listener must not turn into a
    failed transcription.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        on_state_change: Callable[[bool], None] | None = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if not cooldown_seconds > 0:
            raise ValueError("cooldown_seconds must be positive")

        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.on_state_change = on_state_change
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._probing = False

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None

    def admit(self) -> Admission:
        if self._opened_at is None:
            return Admission.SEND
        if self._probing or self._clock() - self._opened_at < self.cooldown_seconds:
            return Admission.REFUSE
        self._probing = True
        return Admission.PROBE

    def record_success(self) -> None:
        """The deployment answered. Closes the breaker from any state.

        A success from a call admitted before the breaker opened counts too:
        it is as much evidence the deployment is back as the probe's is.
        """

        was_open = self._opened_at is not None
        self._failures = 0
        self._opened_at = None
        self._probing = False
        if was_open:
            logger.info("STT circuit closed; the deployment is answering again")
            self._notify(False)

    def record_failure(self, *, trip: bool = False) -> None:
        """One call failed in a way that says the deployment is unwell.

        ``trip`` opens the breaker on this failure alone, for an answer that
        will not change by itself, like a rejected key. A failure while
        already open restarts the cooldown: the deployment was asked again
        and is still not answering.
        """

        self._failures += 1
        if self._opened_at is not None:
            self._opened_at = self._clock()
            self._probing = False
            return
        if trip or self._failures >= self.failure_threshold:
            self._opened_at = self._clock()
            logger.warning(
                "STT circuit opened after %d consecutive failures; "
                "segments fail fast until a probe succeeds",
                self._failures,
            )
            self._notify(True)

    def release_probe(self) -> None:
        """Free the probe slot without a verdict.

        For a probe that ended without saying anything about the deployment
        - cancelled, or refused for a reason of its own. Without this, one
        cancelled probe would leave the slot taken and the breaker refusing
        every call for good, which is worse than having no breaker.
        """

        self._probing = False

    def _notify(self, opened: bool) -> None:
        if self.on_state_change is None:
            return
        try:
            self.on_state_change(opened)
        except Exception:
            logger.exception("STT circuit state listener raised")
