"""The prep poller: Backend's work queue -> :class:`PrepAgent` -> Backend (#176).

Analysis is a job Backend leaves as a database row and the Agent comes to
collect (#137). The row for the pre-interview step appears when a session is
created or a resume is re-uploaded; this process asks for the oldest one,
reads that session's context, runs the preparation and puts the result back.

Three facts about Backend's side shape the loop (#162, #165):

- **Asking does not claim.** ``GET /jobs/pending`` hands out the same job on
  every call until a result is stored or Backend's own time limit (six
  minutes from the request, by default) fails it. So one job is worked
  through at a time, and a job this process could not finish is left alone
  for a while (``retry_after_seconds``) instead of being asked for again at
  the polling rate. The job is not forgotten: Backend still has it, and the
  next ask after the hold gets it back.
- **A result names the request it answers.** ``requestedAt`` from the job
  goes back in the ``PUT`` body, and a 409 means the request was replaced
  while this ran. That result is dropped - the queue holds the replacement.
- **A ``failed`` run is a stored outcome, not a retry.** Backend records it as
  FAILED and the job leaves the queue. So a failure that could answer
  differently next time - the model timed out, the gateway was busy - is not
  stored; the job is held and tried again. A failure that would repeat (no
  competencies, a malformed context) is stored, so the interview does not sit
  in PROCESSING until the time limit does the same thing later and slower.

The mentor's note on the weekly PR (#178) asks that one job's wall time be
measured once the generator is attached, since the no-claim premise holds
only while a job finishes well inside the time limit. Every finished job logs
its agent time and its total time for that reason. Nothing here logs resume
text or a candidate's name; Backend's ids and the outcome are enough to find
a job again.
"""

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic, perf_counter
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import ValidationError

from irya_ai.backend import BackendClient, BackendError
from irya_ai.backend import build_client as build_backend_client
from irya_ai.config import Settings, get_settings
from irya_ai.openai_prep import OpenAIPrepGenerator
from irya_ai.prep import ExtractivePrepGenerator, PrepAgent
from irya_ai.schemas.context import InterviewContext
from irya_ai.schemas.jobs import JOB_KIND_PREP, PendingJob
from irya_ai.schemas.prep import PrepResult
from irya_ai.stt.http_logging import protect_base_url

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_RETRY_AFTER_SECONDS = 30.0
# A job this process will not finish - a kind it does not know, a context it
# cannot read - is left alone this long. Longer than Backend's default limit
# on the request, so Backend fails it first; short enough that a Backend
# restarted with a fix is not waited on for an hour.
DEFAULT_GIVE_UP_SECONDS = 600.0
# ``holds`` is pruned when it grows past this; a few hundred interviews is
# more than one deployment sees in a day.
HOLD_PRUNE_SIZE = 256

Outcome = Literal["idle", "stored", "outdated", "held"]
"""What one pass did: nothing to do, a result stored, a result Backend
refused as outdated, or a job put on hold for later."""


class PollerError(RuntimeError):
    """A job this poller could not turn into a result."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def context_from_response(payload: dict[str, Any]) -> InterviewContext:
    """The :class:`InterviewContext` inside Backend's context answer.

    The answer is the context plus the session's ``utterances`` (#165); the
    context model refuses unknown keys, so the utterances are set aside
    first. Preparation runs before the interview, when that list is empty
    anyway. Anything else that does not fit the model is
    ``CONTEXT_INVALID`` - a contract mismatch, which does not retry.
    """

    fields = {key: value for key, value in payload.items() if key != "utterances"}
    try:
        return InterviewContext.model_validate(fields)
    except ValidationError:
        logger.warning("Backend context did not match InterviewContext")
        raise PollerError("CONTEXT_INVALID", retryable=False) from None


@dataclass(frozen=True)
class Pass:
    """One pass of the loop, for logs and tests."""

    outcome: Outcome
    job: PendingJob | None = None
    result: PrepResult | None = None
    code: str | None = None


class PrepPoller:
    """One job at a time from Backend's queue through the prep agent.

    ``clock`` is monotonic seconds and exists for tests; ``holds`` maps a
    job's key to the clock time before which it is not asked for again.
    """

    def __init__(
        self,
        backend: BackendClient,
        agent: PrepAgent,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        retry_after_seconds: float = DEFAULT_RETRY_AFTER_SECONDS,
        give_up_seconds: float = DEFAULT_GIVE_UP_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must not be negative")
        if give_up_seconds < 0:
            raise ValueError("give_up_seconds must not be negative")
        self.backend = backend
        self.agent = agent
        self.poll_interval_seconds = poll_interval_seconds
        self.retry_after_seconds = retry_after_seconds
        self.give_up_seconds = give_up_seconds
        self._clock = clock
        self.holds: dict[tuple[str, str], float] = {}

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Poll until ``stop`` is set.

        A pass that stored a result asks again at once - another job may be
        waiting behind it. Every other outcome waits out the poll interval
        first. A failure the pass did not classify is logged and treated as
        an idle pass, so one surprise does not end the process.
        """

        while not stop.is_set():
            try:
                done = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must outlive one job
                logger.exception("prep poller pass failed")
                done = Pass("idle")
            if done.outcome in ("stored", "outdated"):
                continue
            try:
                async with asyncio.timeout(self.poll_interval_seconds):
                    await stop.wait()
            except TimeoutError:
                pass

    async def run_once(self) -> Pass:
        """Ask for one job and, if there is one this process can do, do it.

        Raises nothing of its own: a Backend failure on the ask is logged and
        reported as an idle pass, and every failure after that puts the job
        on hold and is reported as ``held``.
        """

        try:
            job = await self.backend.get_pending_job()
        except BackendError as exc:
            logger.warning("prep poll failed: code=%s", exc.code)
            return Pass("idle", code=exc.code)
        if job is None:
            return Pass("idle")
        if self._on_hold(job):
            return Pass("idle", job=job)
        if job.kind != JOB_KIND_PREP:
            # Review jobs arrive on this queue once #164 lands; the generator
            # for them is #170. Until it is wired here, leave them to Backend.
            logger.info(
                "prep poller skipping job kind=%s interview=%s",
                job.kind,
                job.interview_id,
            )
            self._hold(job, self.give_up_seconds)
            return Pass("held", job=job, code="UNSUPPORTED_JOB_KIND")

        started = perf_counter()
        try:
            result = await self._prepare(job)
        except PollerError as exc:
            self._hold_after_failure(job, exc.retryable)
            logger.warning(
                "prep job interview=%s session=%s held code=%s retryable=%s %dms",
                job.interview_id,
                job.session_id,
                exc.code,
                exc.retryable,
                elapsed_ms(started),
            )
            return Pass("held", job=job, code=exc.code)

        if result.status == "failed" and result.error and result.error.retryable:
            # Storing this would fail the interview for good over a moment
            # that may pass. Hold the job and let the next ask try again;
            # Backend's limit still bounds how long that can go on.
            self._hold(job, self.retry_after_seconds)
            logger.warning(
                "prep job interview=%s session=%s held code=%s agent=%dms",
                job.interview_id,
                job.session_id,
                result.error.code,
                result.elapsed_ms,
            )
            return Pass("held", job=job, result=result, code=result.error.code)

        try:
            await self.backend.put_prep(
                job.interview_id, result, requested_at=job.requested_at
            )
        except BackendError as exc:
            if exc.code == "BACKEND_CONFLICT":
                self.holds.pop(job.key, None)
                logger.info(
                    "prep job interview=%s session=%s outdated; dropping result",
                    job.interview_id,
                    job.session_id,
                )
                return Pass("outdated", job=job, result=result, code=exc.code)
            self._hold_after_failure(job, exc.retryable)
            logger.warning(
                "prep job interview=%s session=%s not stored code=%s %dms",
                job.interview_id,
                job.session_id,
                exc.code,
                elapsed_ms(started),
            )
            return Pass("held", job=job, result=result, code=exc.code)

        self.holds.pop(job.key, None)
        logger.info(
            "prep job interview=%s session=%s status=%s competencies=%d claims=%d "
            "rejected=%d agent=%dms total=%dms",
            job.interview_id,
            job.session_id,
            result.status,
            len(result.competencies),
            len(result.resume_claims),
            len(result.rejections),
            result.elapsed_ms,
            elapsed_ms(started),
        )
        if result.error is not None:
            logger.warning(
                "prep job interview=%s stored as failed code=%s",
                job.interview_id,
                result.error.code,
            )
        return Pass("stored", job=job, result=result)

    async def _prepare(self, job: PendingJob) -> PrepResult:
        try:
            payload = await self.backend.get_context(job.session_id)
        except BackendError as exc:
            raise PollerError(exc.code, retryable=exc.retryable) from None
        context = context_from_response(payload)
        if context.session_id != job.session_id:
            # Backend answered about a session nobody asked for. Storing a
            # result under this interview would attach the wrong resume.
            logger.warning("Backend context names a different session than the job")
            raise PollerError("CONTEXT_SESSION_MISMATCH", retryable=False)
        return await self.agent.run(context)

    def _on_hold(self, job: PendingJob) -> bool:
        until = self.holds.get(job.key)
        if until is None:
            return False
        if self._clock() < until:
            return True
        del self.holds[job.key]
        return False

    def _hold(self, job: PendingJob, seconds: float) -> None:
        if len(self.holds) >= HOLD_PRUNE_SIZE:
            now = self._clock()
            self.holds = {k: v for k, v in self.holds.items() if v > now}
        self.holds[job.key] = self._clock() + seconds

    def _hold_after_failure(self, job: PendingJob, retryable: bool) -> None:
        self._hold(job, self.retry_after_seconds if retryable else self.give_up_seconds)


def elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


# --- process -----------------------------------------------------------------


def build_prep_agent(settings: Settings) -> tuple[PrepAgent, AsyncOpenAI | None]:
    """The project LLM when it is configured, the extractive baseline when not.

    Mirrors ``worker.build_suggestion_generator``: the OpenAI-compatible
    client comes back alongside so the caller can close it, ``None`` for the
    baseline. The baseline is for a local run without a key; in production it
    would store sentence lists as competencies, so it logs a warning.
    """

    if settings.llm_base_url and settings.llm_api_key.get_secret_value().strip():
        protect_base_url(settings.llm_base_url)
        client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        generator = OpenAIPrepGenerator(
            client,
            model=settings.llm_model,
            reasoning_effort=settings.llm_reasoning_effort,
        )
        agent = PrepAgent(
            generator,
            model=generator.model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        return agent, client
    logger.warning("LLM not configured; prep poller uses the extractive baseline")
    return PrepAgent(ExtractivePrepGenerator(), model="extractive-baseline"), None


async def serve(settings: Settings, stop: asyncio.Event) -> None:
    """Run the poller against the configured Backend until ``stop`` is set."""

    backend = build_backend_client(settings)
    agent, llm_client = build_prep_agent(settings)
    poller = PrepPoller(
        backend,
        agent,
        poll_interval_seconds=settings.prep_poll_interval_seconds,
        retry_after_seconds=settings.prep_retry_after_seconds,
    )
    logger.info(
        "prep poller started interval=%.1fs retry_after=%.0fs model=%s",
        poller.poll_interval_seconds,
        poller.retry_after_seconds,
        agent.model,
    )
    try:
        await poller.run_forever(stop)
    finally:
        await backend.client.aclose()
        if llm_client is not None:
            await llm_client.close()
        logger.info("prep poller stopped")


def _install_stop(stop: asyncio.Event) -> None:
    """Set ``stop`` on SIGTERM/SIGINT where the loop supports it (not Windows)."""

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError):
            # Windows: Ctrl-C arrives as KeyboardInterrupt in ``main`` instead.
            return


async def _main(settings: Settings) -> None:
    stop = asyncio.Event()
    _install_stop(stop)
    await serve(settings, stop)


def main() -> int:
    """``irya-ai-poller`` / ``python -m irya_ai.prep_poller``."""

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(_main(settings))
    except BackendError as exc:
        # ``BACKEND_BASE_URL_NOT_SET``: there is nothing to poll.
        logger.error("prep poller cannot start: %s", exc.code)
        return 2
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
