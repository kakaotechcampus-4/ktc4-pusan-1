"""Queue FINAL utterances away from the media path, then use TranscriptChannel.

The channel owns ACK/NACK and reconnect buffering. This runner only keeps its
network waits out of the caption/STT sinks. Shutdown drains queued sends before
closing the channel (which waits for ACKs); it does not establish that all STT
tracks finished or that a REVIEW job may start (#137's open completion barrier).
"""

import asyncio
import logging

from irya_ai.backend import BackendError
from irya_ai.schemas.transcript import Utterance
from irya_ai.schemas.wire import transcript_payload
from irya_ai.transcripts import TranscriptChannel

logger = logging.getLogger(__name__)


class TranscriptRunner:
    """One bounded queue and sender task per session; admission never waits."""

    def __init__(
        self, channel: TranscriptChannel, *, session_id: str, max_queue: int = 200
    ) -> None:
        if max_queue < 1:
            raise ValueError("max_queue must be positive")
        self.channel = channel
        self.session_id = session_id
        self._queue: asyncio.Queue[Utterance] = asyncio.Queue(maxsize=max_queue)
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self.dropped = 0
        self.send_failures = 0

    async def __call__(self, utterance: Utterance) -> None:
        if not utterance.is_final:
            return
        if self._closed or utterance.session_id != self.session_id:
            self._drop("closed or wrong session")
            return
        try:
            self._queue.put_nowait(utterance)
        except asyncio.QueueFull:
            self._drop("queue full")

    def _drop(self, reason: str, *, count: int = 1) -> None:
        self.dropped += count
        logger.warning(
            "transcript dropped session=%s reason=%s count=%d total=%d",
            self.session_id,
            reason,
            count,
            self.dropped,
        )

    def start(self) -> asyncio.Task[None]:
        if self._closed:
            raise RuntimeError("transcript runner is closed")
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(), name=f"transcripts-{self.session_id}"
            )
        return self._task

    async def _run(self) -> None:
        while True:
            utterance = await self._queue.get()
            try:
                payload = transcript_payload(
                    utterance, participant_id=utterance.speaker.value
                )
                await self.channel.send(payload)
            except BackendError as exc:
                self.send_failures += 1
                # Retryable failures leave the frame in the channel's buffer.
                # A full buffer or a permanent refusal cannot retain this send.
                if not exc.retryable or exc.code == "BACKEND_TRANSCRIPT_BUFFER_FULL":
                    self._drop(exc.code)
                logger.warning(
                    "transcript send failed session=%s code=%s pending=%d",
                    self.session_id,
                    exc.code,
                    self.channel.unacknowledged,
                )
            except Exception as exc:  # noqa: BLE001 - keep the sender alive
                self.send_failures += 1
                self._drop(type(exc).__name__)
                # Validation errors can contain the transcript. Log only the
                # exception type, never its message or traceback.
            finally:
                self._queue.task_done()

    async def stop(self, *, timeout: float = 5.0) -> None:
        """Drain admitted sends within a bound, cancel, then wait for ACKs."""
        if self._closed:
            return
        self._closed = True
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout)
            except TimeoutError:
                logger.warning(
                    "transcript sender drain timed out session=%s pending=%d",
                    self.session_id,
                    self._queue.qsize(),
                )
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        remaining = self._queue.qsize()
        if remaining:
            self._drop("shutdown queue", count=remaining)
            while not self._queue.empty():
                self._queue.get_nowait()
                self._queue.task_done()
        await self.channel.aclose()
        logger.info(
            "transcript sender closed session=%s dropped=%d refused=%d pending=%d",
            self.session_id,
            self.dropped,
            len(self.channel.refused),
            self.channel.unacknowledged,
        )
