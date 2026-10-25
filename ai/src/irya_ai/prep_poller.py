"""The prep poller: Backend's work queue -> the analysis agents -> Backend (#176).

Analysis is a job Backend leaves as a database row and the Agent comes to
collect (#137). A ``PREP`` row appears when a session is created or a resume
is re-uploaded; this process asks for the oldest one, reads that session's
context, runs the preparation and puts the result back at ``.../prep``. A
``REVIEW`` row appears when the interview ends (#164); the same context
answer carries the interview's utterances, and the summary, timeline and
findings run on them side by side and go back as one ``.../review`` (#220).
Both kinds share the rules below.

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
  competencies, a malformed context, a session Backend does not know) is
  stored, so the interview does not sit in PROCESSING until the time limit
  does the same thing later and slower.
- **The oldest job is the only job.** Backend hands out the oldest PROCESSING
  row and nothing else, so a job left in the queue blocks every job behind
  it (head-of-line). That is the other reason a failure that would repeat is
  stored rather than held: a hold would stall the healthy interviews behind
  it until Backend's limit cleared the way, by which time theirs may have run
  out too. The only jobs still held for long are ones this process cannot
  even store a result for - a kind it does not handle, a ``PUT`` Backend
  refuses - and those are logged as errors, because the queue is stuck.

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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic, perf_counter
from typing import Any, Literal, Protocol

from openai import AsyncOpenAI
from pydantic import ValidationError

from irya_ai.analysis import ContextAnalysisAgent
from irya_ai.backend import BackendClient, BackendError
from irya_ai.backend import build_client as build_backend_client
from irya_ai.config import Settings, get_settings
from irya_ai.openai_prep import OpenAIPrepGenerator
from irya_ai.openai_summary import OpenAISummarizer
from irya_ai.openai_timeline import OpenAITimelineGenerator
from irya_ai.prep import ExtractivePrepGenerator, PrepAgent
from irya_ai.schemas.analysis import Finding
from irya_ai.schemas.context import InterviewContext
from irya_ai.schemas.jobs import JOB_KIND_PREP, JOB_KIND_REVIEW, PendingJob
from irya_ai.schemas.prep import PrepResult
from irya_ai.schemas.summary import AnalysisError, AnalysisResult
from irya_ai.schemas.timeline import TimelineResult
from irya_ai.schemas.transcript import TranscriptSnapshot, TranscriptStage, Utterance
from irya_ai.schemas.wire import ReviewPayload, review_payload
from irya_ai.stt.http_logging import protect_base_url
from irya_ai.summarize import ExtractiveSummarizer
from irya_ai.timeline import ExtractiveTimelineGenerator, ReviewTimelineAgent

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_RETRY_AFTER_SECONDS = 30.0
# A job this process can neither finish nor fail - a kind it does not know,
# a result Backend refuses to store - is left alone this long. Longer than
# Backend's default limit on the request, so Backend fails it first; short
# enough that a Backend restarted with a fix is not waited on for an hour.
# While it lasts the queue behind the job is stuck (see the module note).
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


UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


def exception_types(exc: BaseException) -> str:
    """The type names behind ``exc``, opened up when a ``TaskGroup`` grouped them."""

    if isinstance(exc, BaseExceptionGroup):
        return ",".join(exception_types(inner) for inner in exc.exceptions)
    return type(exc).__name__


@dataclass(frozen=True)
class Pass:
    """One pass of the loop, for logs and tests."""

    outcome: Outcome
    job: PendingJob | None = None
    result: PrepResult | ReviewPayload | None = None
    code: str | None = None


# --- review --------------------------------------------------------------------

# The keys of an ``Utterance`` as Backend spells them. Backend's utterance rows
# may grow fields (a creation time, a pass type) that the transcript model
# refuses, so the rest are dropped before validation rather than failing the
# whole review over a column this process does not read.
UTTERANCE_KEYS = frozenset(
    field.alias or name for name, field in Utterance.model_fields.items()
)


def snapshot_from_response(
    payload: dict[str, Any], session_id: str
) -> TranscriptSnapshot:
    """The interview's transcript from Backend's context answer.

    Backend keeps the FINAL utterances the worker sent during the call, so
    the snapshot is ``LIVE``; the recording-aligned transcript is a later
    issue. An empty list is a valid snapshot - the summary comes back
    ``empty`` and that is stored. A list that does not fit the model is
    ``TRANSCRIPT_INVALID``, which does not retry.

    Rows saved before #158 have no ``trackId`` or ``seq``. Those are filled
    from the speaker and from Backend's order, so one old row does not fail
    the whole review.
    """

    rows = payload.get("utterances") or []
    try:
        utterances = [
            {key: value for key, value in row.items() if key in UTTERANCE_KEYS}
            for row in rows
        ]
        filled = fill_missing_identity(utterances)
        if filled:
            logger.warning(
                "Backend utterances missing trackId or seq: filled=%d of %d",
                filled,
                len(utterances),
            )
        return TranscriptSnapshot.model_validate(
            {
                "sessionId": session_id,
                "stage": TranscriptStage.LIVE,
                "utterances": utterances,
            }
        )
    except (ValidationError, AttributeError, TypeError):
        logger.warning("Backend utterances did not match TranscriptSnapshot")
        raise PollerError("TRANSCRIPT_INVALID", retryable=False) from None


def fill_missing_identity(utterances: list[dict[str, Any]]) -> int:
    """Fill a null ``trackId`` or ``seq`` in place; return how many rows.

    A missing track becomes ``trk_<speaker>``. A missing ``seq`` becomes the
    row's place in Backend's list, kept for every revision of one utterance
    so the snapshot still sees them as the same utterance.
    """

    filled = 0
    first_index: dict[Any, int] = {}
    for index, row in enumerate(utterances):
        first = first_index.setdefault(row.get("utteranceId"), index)
        missing = False
        if row.get("trackId") is None and isinstance(row.get("speaker"), str):
            row["trackId"] = f"trk_{row['speaker'].lower()}"
            missing = True
        if row.get("seq") is None:
            row["seq"] = first
            missing = True
        filled += missing
    return filled


class FindingsOutcome(Protocol):
    status: str
    findings: list[Finding]
    error: AnalysisError | None
    elapsed_ms: int


class FindingsRunner(Protocol):
    """The findings agent (#166), once it lands; ``FindingsAgent.run``."""

    async def run(
        self, context: InterviewContext, snapshot: TranscriptSnapshot
    ) -> FindingsOutcome: ...


@dataclass(frozen=True)
class ReviewParts:
    """What the review agents returned for one job, or why they did not run."""

    summary: AnalysisResult | None = None
    timeline: TimelineResult | None = None
    findings: FindingsOutcome | None = None
    agent_ms: int = 0
    error_code: str | None = None

    def _parts(self) -> list[tuple[str, Any]]:
        named = [
            ("summary", self.summary),
            ("timeline", self.timeline),
            ("findings", self.findings),
        ]
        return [(name, part) for name, part in named if part is not None]

    def retryable_failure(self) -> str | None:
        """The code of the first part that failed for a reason that may pass."""

        for _, part in self._parts():
            if part.status == "failed" and part.error and part.error.retryable:
                return part.error.code
        return None

    def payload(self, *, model: str) -> ReviewPayload:
        assert self.summary is not None
        findings = None
        if self.findings is not None and self.findings.status != "failed":
            findings = list(self.findings.findings)
        return review_payload(
            self.summary, self.timeline, findings=findings, model=model
        )

    def log_fields(self) -> str:
        """Statuses, counts and times; never the summary or a quote."""

        fields = []
        if self.summary is not None:
            points = self.summary.summary_result
            fields.append(
                f"summary={self.summary.status}"
                f" points={len(points.points) if points else 0}"
                f" summary_ms={self.summary.elapsed_ms}"
            )
        if self.timeline is not None:
            fields.append(
                f"timeline={self.timeline.status}"
                f" moments={len(self.timeline.moments)}"
                f" timeline_ms={self.timeline.elapsed_ms}"
            )
        if self.findings is not None:
            fields.append(
                f"findings={self.findings.status}"
                f" count={len(self.findings.findings)}"
                f" findings_ms={self.findings.elapsed_ms}"
            )
        errors = [
            f"{name}:{part.error.code}" for name, part in self._parts() if part.error
        ]
        if errors:
            fields.append("errors=" + ",".join(errors))
        fields.append(f"agent={self.agent_ms}ms")
        return " ".join(fields)


@dataclass(frozen=True)
class ReviewAgents:
    """The post-interview analysis: summary, timeline and, when wired, findings.

    The three read the same transcript and nothing of each other, so they run
    side by side. Backend's limit on a REVIEW request counts from the end of
    the interview, and one after another they would spend it three times.
    """

    summary: ContextAnalysisAgent
    timeline: ReviewTimelineAgent
    findings: FindingsRunner | None = None
    model: str = ""

    async def run(
        self, context: InterviewContext, snapshot: TranscriptSnapshot
    ) -> ReviewParts:
        started = perf_counter()
        # A TaskGroup rather than ``gather``: if one agent raises, the others
        # are cancelled instead of left running with nobody to read them.
        async with asyncio.TaskGroup() as group:
            summary = group.create_task(self.summary.analyze(snapshot))
            timeline = group.create_task(self.timeline.run(snapshot))
            findings = (
                group.create_task(self.findings.run(context, snapshot))
                if self.findings is not None
                else None
            )
        return ReviewParts(
            summary=summary.result(),
            timeline=timeline.result(),
            findings=findings.result() if findings is not None else None,
            agent_ms=elapsed_ms(started),
        )


class PrepPoller:
    """One job at a time from Backend's queue through the prep or review agents.

    ``review`` is ``None`` in a process that only prepares; a REVIEW job is
    then held like any other kind it cannot do.

    ``clock`` is monotonic seconds and exists for tests; ``holds`` maps a
    job's key to the clock time before which it is not asked for again.
    """

    def __init__(
        self,
        backend: BackendClient,
        agent: PrepAgent,
        *,
        review: ReviewAgents | None = None,
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
        self.review = review
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
        try:
            if job.kind == JOB_KIND_PREP:
                return await self._run_prep(job)
            if job.kind == JOB_KIND_REVIEW and self.review is not None:
                return await self._run_review(job)
        except Exception as exc:  # noqa: BLE001 - one job must not stall the loop
            # A failure outside the agents, which store their own. Without a
            # hold the next poll would hand out the same job at the poll rate.
            # Only the type is logged: the message may quote the transcript.
            self._hold(job, self.retry_after_seconds)
            logger.error(
                "%s job interview=%s session=%s held after unexpected %s",
                job.kind.lower(),
                job.interview_id,
                job.session_id,
                exception_types(exc),
            )
            return Pass("held", job=job, code=UNEXPECTED_ERROR)
        # A kind this process has nothing to store for. Backend hands out
        # every kind on one ask, so while it is held it blocks the jobs
        # behind it; the hold is long and the log is an error for that reason.
        logger.error(
            "prep poller cannot handle job kind=%s interview=%s; "
            "the queue behind it waits",
            job.kind,
            job.interview_id,
        )
        self._hold(job, self.give_up_seconds)
        return Pass("held", job=job, code="UNSUPPORTED_JOB_KIND")

    async def _run_prep(self, job: PendingJob) -> Pass:
        started = perf_counter()
        try:
            result = await self._prepare(job)
        except PollerError as exc:
            if exc.retryable:
                return self._held_before_store(job, exc.code, started)
            # Asking again would fail the same way, and a held job blocks the
            # queue behind it. Store the failure so the row leaves the queue.
            result = self._failed_result(job, exc.code)
        except Exception as exc:  # noqa: BLE001 - see _unexpected
            self._unexpected(job, exc)
            result = self._failed_result(job, UNEXPECTED_ERROR)

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

        refused = await self._store(
            job,
            self.backend.put_prep(
                job.interview_id, result, requested_at=job.requested_at
            ),
            result,
            started,
        )
        if refused is not None:
            return refused
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

    async def _run_review(self, job: PendingJob) -> Pass:
        assert self.review is not None
        started = perf_counter()
        try:
            context, snapshot = await self._review_input(job)
        except PollerError as exc:
            if exc.retryable:
                return self._held_before_store(job, exc.code, started)
            parts = ReviewParts(error_code=exc.code)
        else:
            try:
                parts = await self.review.run(context, snapshot)
            except Exception as exc:  # noqa: BLE001 - see _unexpected
                self._unexpected(job, exc)
                parts = ReviewParts(error_code=UNEXPECTED_ERROR)
        if parts.error_code is not None:
            payload = ReviewPayload(status="failed", model=self.review.model)
        else:
            retry = parts.retryable_failure()
            if retry is not None:
                # One part failed in a way that may pass. Storing now would
                # keep the other two and lose this one for good, so the whole
                # job waits; Backend's limit bounds how long.
                self._hold(job, self.retry_after_seconds)
                logger.warning(
                    "review job interview=%s session=%s held code=%s %s",
                    job.interview_id,
                    job.session_id,
                    retry,
                    parts.log_fields(),
                )
                return Pass("held", job=job, code=retry)
            payload = parts.payload(model=self.review.model)

        refused = await self._store(
            job,
            self.backend.put_review(
                job.session_id, payload, requested_at=job.requested_at
            ),
            payload,
            started,
        )
        if refused is not None:
            return refused
        logger.info(
            "review job interview=%s session=%s status=%s %s total=%dms",
            job.interview_id,
            job.session_id,
            payload.status,
            parts.log_fields(),
            elapsed_ms(started),
        )
        if parts.error_code is not None:
            logger.warning(
                "review job interview=%s stored as failed code=%s",
                job.interview_id,
                parts.error_code,
            )
        return Pass("stored", job=job, result=payload)

    def _unexpected(self, job: PendingJob, exc: Exception) -> None:
        """Log an agent failure no step classified; the caller stores it.

        A bug raises the same way on every try, so holding and asking again
        would only run the model again until Backend gives up. Only the types
        are logged: the message may quote the transcript or the resume.
        """

        logger.error(
            "%s job interview=%s session=%s failed with unexpected %s",
            job.kind.lower(),
            job.interview_id,
            job.session_id,
            exception_types(exc),
        )

    def _held_before_store(self, job: PendingJob, code: str, started: float) -> Pass:
        """Hold a job whose input could not be read for a reason that may pass."""

        self._hold(job, self.retry_after_seconds)
        logger.warning(
            "%s job interview=%s session=%s held code=%s %dms",
            job.kind.lower(),
            job.interview_id,
            job.session_id,
            code,
            elapsed_ms(started),
        )
        return Pass("held", job=job, code=code)

    async def _store(
        self,
        job: PendingJob,
        put: Awaitable[None],
        result: PrepResult | ReviewPayload,
        started: float,
    ) -> Pass | None:
        """Await one ``PUT``; ``None`` when stored, the pass to report when not."""

        kind = job.kind.lower()
        try:
            await put
        except BackendError as exc:
            if exc.code == "BACKEND_CONFLICT":
                self.holds.pop(job.key, None)
                logger.info(
                    "%s job interview=%s session=%s outdated; dropping result",
                    kind,
                    job.interview_id,
                    job.session_id,
                )
                return Pass("outdated", job=job, result=result, code=exc.code)
            if exc.retryable:
                self._hold(job, self.retry_after_seconds)
                logger.warning(
                    "%s job interview=%s session=%s not stored code=%s %dms",
                    kind,
                    job.interview_id,
                    job.session_id,
                    exc.code,
                    elapsed_ms(started),
                )
            else:
                # Backend will not take a result for this job, so nothing
                # this process does moves it out of the queue. Hold it for
                # the long wait and say so loudly: everything behind it waits.
                self._hold(job, self.give_up_seconds)
                logger.error(
                    "%s job interview=%s session=%s refused code=%s; "
                    "the queue behind it waits",
                    kind,
                    job.interview_id,
                    job.session_id,
                    exc.code,
                )
            return Pass("held", job=job, result=result, code=exc.code)
        self.holds.pop(job.key, None)
        return None

    async def _review_input(
        self, job: PendingJob
    ) -> tuple[InterviewContext, TranscriptSnapshot]:
        try:
            payload = await self.backend.get_context(job.session_id)
        except BackendError as exc:
            raise PollerError(exc.code, retryable=exc.retryable) from None
        context = context_from_response(payload)
        if context.session_id != job.session_id:
            logger.warning("Backend context names a different session than the job")
            raise PollerError("CONTEXT_SESSION_MISMATCH", retryable=False)
        return context, snapshot_from_response(payload, job.session_id)

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

    def _failed_result(self, job: PendingJob, code: str) -> PrepResult:
        """A ``failed`` result for a job the agent never saw.

        Carries the job's own session id, not whatever Backend answered with,
        so a mismatched context is recorded against the interview that asked.
        """

        return PrepResult(
            session_id=job.session_id,
            status="failed",
            model=self.agent.model,
            error=AnalysisError(code=code, retryable=False),
        )


def elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


# --- process -----------------------------------------------------------------


def build_agents(
    settings: Settings,
) -> tuple[PrepAgent, ReviewAgents, AsyncOpenAI | None]:
    """The project LLM when it is configured, the extractive baselines when not.

    Mirrors ``worker.build_suggestion_generator``: the OpenAI-compatible
    client comes back alongside so the caller can close it, ``None`` for the
    baselines. Preparation and review share the one client. The baselines
    are for a local run without a key; in production they would store
    sentence lists as competencies and summaries, so they log a warning.
    """

    if settings.llm_base_url and settings.llm_api_key.get_secret_value().strip():
        protect_base_url(settings.llm_base_url)
        client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        prep = OpenAIPrepGenerator(
            client,
            model=settings.llm_model,
            reasoning_effort=settings.llm_reasoning_effort,
        )
        timeline = OpenAITimelineGenerator(
            client,
            model=settings.llm_model,
            reasoning_effort=settings.llm_reasoning_effort,
        )
        agent = PrepAgent(
            prep, model=prep.model, timeout_seconds=settings.llm_timeout_seconds
        )
        review = ReviewAgents(
            summary=ContextAnalysisAgent(
                # Reasoning tokens share the 2000-token reply ceiling; "low"
                # cut a summary to about two thirds without losing points.
                OpenAISummarizer(
                    client, model=settings.llm_model, reasoning_effort="low"
                ),
                timeout_seconds=settings.llm_timeout_seconds,
            ),
            timeline=ReviewTimelineAgent(
                timeline,
                model=timeline.model,
                timeout_seconds=settings.llm_timeout_seconds,
            ),
            model=settings.llm_model,
        )
        return agent, review, client
    logger.warning("LLM not configured; prep poller uses the extractive baselines")
    review = ReviewAgents(
        summary=ContextAnalysisAgent(ExtractiveSummarizer()),
        timeline=ReviewTimelineAgent(
            ExtractiveTimelineGenerator(), model="extractive-baseline"
        ),
        model="extractive-baseline",
    )
    return (
        PrepAgent(ExtractivePrepGenerator(), model="extractive-baseline"),
        review,
        None,
    )


async def serve(settings: Settings, stop: asyncio.Event) -> None:
    """Run the poller against the configured Backend until ``stop`` is set."""

    backend = build_backend_client(settings)
    agent, review, llm_client = build_agents(settings)
    poller = PrepPoller(
        backend,
        agent,
        review=review,
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
