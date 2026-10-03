"""IRYA LiveKit STT worker.

Run locally with ``uv run python -m irya_ai.worker dev`` and in production
with ``python -m irya_ai.worker start``. The worker is unnamed on purpose:
the current single-product LiveKit deployment automatically dispatches it to
new rooms. Explicit backend dispatch can replace that when more agent types
share the server.

One room is one job. The job builds one Elice STT client, hands it to a
:class:`~irya_ai.stt.rtc_bridge.RoomTranscriber`, and lets that transcribe
each human microphone through the Whisper live path. Every released
utterance goes through one :class:`~irya_ai.sinks.FanOutSink` to the
interviewer's caption and, when a Backend is configured, to the follow-up
question loop (:mod:`irya_ai.suggestion_runner`), whose kept suggestions are
posted to ``/internal/v1``. The Backend transcript channel is not attached
here yet.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from livekit.agents import (
    AgentServer,
    AutoSubscribe,
    JobContext,
    WorkerPermissions,
    cli,
)
from openai import AsyncOpenAI

from irya_ai.backend import BackendError
from irya_ai.backend import build_client as build_backend_client
from irya_ai.config import Settings, get_settings
from irya_ai.openai_suggestions import OpenAISuggestionGenerator
from irya_ai.sinks import FanOutSink
from irya_ai.stt.elice import EliceSttClient, SttError, build_client
from irya_ai.stt.rtc_bridge import RoomTranscriber, session_id_from_room
from irya_ai.stt.stream import silent_probe
from irya_ai.suggestion_runner import SuggestionRunner
from irya_ai.suggestions import (
    ExtractiveSuggestionGenerator,
    LiveSuggestionAgent,
    SuggestionGenerator,
)

logger = logging.getLogger(__name__)

#: How long one follow-up round may take before the agent gives up on it.
#: Deliberately shorter than ``LLM_TIMEOUT_SECONDS`` (which bounds the review
#: paths): a suggestion that arrives after the interviewer has moved on is
#: worth nothing, and TechSpec N3 asks for it within 3 seconds of the moment.
#: The round is not retried on the same words either way.
SUGGESTION_ROUND_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class SuggestionWiring:
    """The follow-up loop for one room and how to take it down."""

    runner: SuggestionRunner
    generator_name: str
    close: Callable[[], Awaitable[None]]


def build_suggestion_generator(
    settings: Settings,
) -> tuple[SuggestionGenerator, AsyncOpenAI | None]:
    """The project LLM when it is configured, the extractive baseline when not.

    Returns the OpenAI-compatible client alongside so the caller can close it;
    ``None`` for the baseline, which owns nothing.
    """

    if settings.llm_base_url and settings.llm_api_key.get_secret_value().strip():
        client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        generator = OpenAISuggestionGenerator(
            client,
            model=settings.llm_model,
            reasoning_effort=settings.llm_reasoning_effort,
        )
        return generator, client
    return ExtractiveSuggestionGenerator(), None


def wire_suggestions(settings: Settings, *, session_id: str) -> SuggestionWiring | None:
    """Assemble the follow-up loop for one room, or ``None`` without a Backend.

    Suggestions only exist to be posted, so an unset ``BACKEND_BASE_URL``
    disables the whole loop rather than running rounds nobody receives. The
    captions do not depend on this and continue either way.
    """

    try:
        backend = build_backend_client(settings)
    except BackendError as exc:
        logger.info(
            "suggestions disabled (%s); captions continue session=%s",
            exc.code,
            session_id,
        )
        return None

    generator, llm_client = build_suggestion_generator(settings)
    agent = LiveSuggestionAgent(
        generator,
        model=getattr(generator, "model", ""),
        timeout_seconds=SUGGESTION_ROUND_TIMEOUT_SECONDS,
    )
    runner = SuggestionRunner(
        agent, session_id=session_id, post=backend.post_suggestion
    )

    async def close() -> None:
        # Drain first, then take the clients away: a post in flight when the
        # room ends should reach the Backend rather than die on a closed
        # client.
        await runner.stop()
        await backend.client.aclose()
        if llm_client is not None:
            await llm_client.close()

    return SuggestionWiring(
        runner=runner,
        generator_name=type(generator).__name__,
        close=close,
    )


async def _warm_up(client: EliceSttClient) -> None:
    """Take the deployment's cold start before the first real segment, if it can.

    Runs beside the connect rather than before it: a room that is waiting on
    a warm-up it does not need is worse than a first segment that pays it.
    """

    try:
        await client.warm_up(silent_probe())
    except Exception:  # noqa: BLE001 - best effort, nothing depends on it
        logger.exception("STT warm-up raised; continuing without it")


async def transcribe_room(ctx: JobContext) -> None:
    """Run one isolated STT job for one IRYA room."""

    session_id = session_id_from_room(ctx.room.name)
    if session_id is None:
        logger.warning("ignoring room outside IRYA naming rule room=%s", ctx.room.name)
        ctx.shutdown("unsupported room")
        return

    settings = get_settings()
    ctx.log_context_fields = {"room": ctx.room.name, "session_id": session_id}
    try:
        client = build_client(settings)
    except SttError as exc:
        # No deployment to send audio to. Leaving the room is the honest
        # outcome; staying would look like a transcriber that hears nothing.
        logger.error(
            "STT is not configured (%s); leaving room=%s", exc.code, ctx.room.name
        )
        ctx.shutdown("stt not configured")
        return
    ctx.add_shutdown_callback(client.client.aclose)

    transcriber = RoomTranscriber(
        room=ctx.room,
        session_id=session_id,
        client=client,
    )
    # The caption stays first so the interviewer sees the words before any
    # consumer that reasons about them; the fan-out keeps one consumer's
    # failure from ending the track for the others.
    wiring = wire_suggestions(settings, session_id=session_id)
    consumers = [transcriber.caption]
    if wiring is not None:
        consumers.append(wiring.runner)
        ctx.add_shutdown_callback(wiring.close)
    transcriber.sinks = [FanOutSink(consumers)]

    async def transcribe_participant(_ctx: JobContext, participant) -> None:
        await transcriber.transcribe_participant(participant)

    # Register before connect so existing and later participants both get one
    # long-lived callback. The callbacks wait until t=0 is initialized.
    ctx.add_participant_entrypoint(transcribe_participant)
    warm_up = asyncio.create_task(_warm_up(client), name="stt-warm-up")
    ctx.add_shutdown_callback(lambda: _cancel(warm_up))
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    if wiring is not None:
        wiring.runner.start()
    origin = transcriber.initialize_origin(ctx.room.remote_participants.values())
    logger.info(
        "joined room=%s session=%s participants=%d origin=%s suggestions=%s",
        ctx.room.name,
        session_id,
        len(ctx.room.remote_participants),
        origin.isoformat() if origin else "pending first human",
        wiring.generator_name if wiring is not None else "off",
    )


async def _cancel(task: asyncio.Task[None]) -> None:
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def create_server(settings: Settings | None = None) -> AgentServer:
    """Build the process pool and register the room entrypoint."""

    settings = settings or get_settings()
    server = AgentServer(
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key.get_secret_value(),
        api_secret=settings.livekit_api_secret.get_secret_value(),
        num_idle_processes=1,
        permissions=WorkerPermissions(
            can_publish=False,
            can_subscribe=True,
            can_publish_data=True,
            can_update_metadata=False,
            hidden=True,
        ),
        log_level=settings.log_level,
    )
    server.rtc_session(transcribe_room)
    return server


def main() -> None:
    cli.run_app(create_server())


if __name__ == "__main__":
    main()
