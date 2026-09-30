"""Run the follow-up question agent beside a live transcript, off the audio path.

The worker releases utterances from inside its audio pipeline, where nothing
may wait on a model or a remote service (#73 review point 1). The agent's
:meth:`~irya_ai.suggestions.LiveSuggestionAgent.run_round` waits on both.
This module keeps the two apart with the smallest possible structure: one
queue and one task per session.

The sink side (:meth:`SuggestionRunner.__call__`) puts the utterance on the
queue and returns. The task side (:meth:`SuggestionRunner.run`) drains the
queue through :meth:`~irya_ai.suggestions.LiveSuggestionAgent.ingest`, asks
:meth:`~irya_ai.suggestions.LiveSuggestionAgent.due` once, and only then
runs a round and posts what it kept. Utterances that arrive while a round is
running wait in the queue and are all ingested before the next ``due``, so
a slow model delays rounds but never loses speech.

Posting goes through :meth:`~irya_ai.backend.BackendClient.post_suggestion`,
whose contract already says what a final failure costs: a suggestion is only
worth anything while the answer that prompted it is on screen, so a failed
post is logged and dropped, not replayed.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from irya_ai.backend import BackendError
from irya_ai.schemas.suggestion import SuggestionResult
from irya_ai.schemas.transcript import Utterance
from irya_ai.schemas.wire import SuggestionPayload, suggestion_payload
from irya_ai.suggestions import LiveSuggestionAgent

logger = logging.getLogger(__name__)

#: Utterances the queue holds before the sink starts dropping. A FINAL
#: utterance arrives every few seconds and a round takes seconds, so the
#: queue is normally a handful deep; reaching this means the consumer is
#: stuck, and blocking the audio path behind it would be worse than losing
#: the utterance's contribution to a suggestion.
DEFAULT_MAX_QUEUE = 256

#: How long :meth:`SuggestionRunner.stop` lets a round in flight finish
#: before cancelling it. A room that has ended has nobody left to show a
#: suggestion to, so this is about not cutting a Backend post in half, not
#: about completing the round.
DEFAULT_STOP_TIMEOUT_SECONDS = 5.0

Poster = Callable[[str, SuggestionPayload], Awaitable[None]]


class SuggestionRunner:
    """One session's suggestion loop: a sink that queues, a task that runs.

    ``post`` is :meth:`~irya_ai.backend.BackendClient.post_suggestion` or a
    stand-in with the same shape. It is awaited for each kept suggestion in
    the order the round produced them; a :class:`~irya_ai.backend.BackendError`
    is logged and the rest of the round still goes out. Any other exception
    from the model, the agent or the poster is logged with its traceback and
    the loop continues with the next utterance (TechSpec N4).
    """

    def __init__(
        self,
        agent: LiveSuggestionAgent,
        *,
        session_id: str,
        post: Poster,
        max_queue: int = DEFAULT_MAX_QUEUE,
    ) -> None:
        if max_queue < 1:
            raise ValueError("max_queue must be at least 1")
        self.agent = agent
        self.session_id = session_id
        self.post = post
        self._queue: asyncio.Queue[Utterance] = asyncio.Queue(maxsize=max_queue)
        self._task: asyncio.Task[None] | None = None
        #: Utterances the sink could not queue because the consumer was stuck.
        self.dropped = 0
        #: Rounds run, suggestions posted, posts that failed for good.
        self.rounds = 0
        self.posted = 0
        self.post_failures = 0
        self.results: list[SuggestionResult] = []

    # --- the sink side: called from the audio path -------------------------

    async def __call__(self, utterance: Utterance) -> None:
        """Queue one utterance. Never waits: the audio path is the caller."""

        try:
            self._queue.put_nowait(utterance)
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning(
                "suggestion queue full; dropping utterance=%s session=%s dropped=%d",
                utterance.utterance_id,
                self.session_id,
                self.dropped,
            )

    # --- the task side --------------------------------------------------------

    def start(self) -> asyncio.Task[None]:
        """Start the consumer task. Idempotent while it is running."""

        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self.run(), name=f"suggestions-{self.session_id}"
            )
        return self._task

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self, *, timeout: float = DEFAULT_STOP_TIMEOUT_SECONDS) -> None:
        """Let the queue drain and any round in flight finish, then cancel.

        Waits up to ``timeout`` for the queue to empty and the current round
        to post; the task is then cancelled whether or not it got there. A
        runner that was never started is a no-op.
        """

        task = self._task
        if task is None:
            return
        if not task.done():
            try:
                await asyncio.wait_for(self._queue.join(), timeout=timeout)
            except TimeoutError:
                logger.warning(
                    "suggestion runner did not drain in %.1fs; cancelling "
                    "session=%s pending=%d",
                    timeout,
                    self.session_id,
                    self._queue.qsize(),
                )
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def run(self) -> None:
        """Consume the queue until cancelled. Exposed for tests; use :meth:`start`."""

        while True:
            first = await self._queue.get()
            taken = 1
            try:
                self.agent.ingest(first)
                # Everything that arrived meanwhile - during the last round,
                # say - goes in before the question is asked, so ``due`` sees
                # the answer as it stands rather than as it was.
                while True:
                    try:
                        later = self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    taken += 1
                    self.agent.ingest(later)
                pair = self.agent.due()
                if pair is not None:
                    await self._round(pair)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop outlives any one failure
                logger.exception(
                    "suggestion round failed; continuing session=%s", self.session_id
                )
            finally:
                for _ in range(taken):
                    self._queue.task_done()

    async def _round(self, pair) -> None:
        result = await self.agent.run_round(pair)
        self.rounds += 1
        self.results.append(result)
        logger.info(
            "suggestion round session=%s qa=%s status=%s kept=%d rejected=%d %dms",
            self.session_id,
            pair.qa_id,
            result.status,
            len(result.suggestions),
            len(result.rejections),
            result.elapsed_ms,
        )
        for question in result.suggestions:
            payload = suggestion_payload(question)
            try:
                await self.post(self.session_id, payload)
            except BackendError as exc:
                # ``post_suggestion`` has already retried what was worth
                # retrying and logged the code. The suggestion is stale by
                # the time a replay could land, so it is dropped here.
                self.post_failures += 1
                logger.warning(
                    "suggestion dropped after Backend failure session=%s "
                    "suggestion=%s code=%s",
                    self.session_id,
                    payload.suggestion_id,
                    exc.code,
                )
            else:
                self.posted += 1
