"""IRYA LiveKit STT worker.

Run locally with ``uv run python -m irya_ai.worker dev`` and in production
with ``python -m irya_ai.worker start``. The worker is unnamed on purpose:
the current single-product LiveKit deployment automatically dispatches it to
new rooms. Explicit backend dispatch can replace that when more agent types
share the server.

One room is one job. The job builds one Elice STT client, hands it to a
:class:`~irya_ai.stt.rtc_bridge.RoomTranscriber`, and lets that transcribe
each human microphone through the Whisper live path. Nothing else runs here:
the follow-up question agent and the Backend transcript channel attach to the
transcriber's sinks in their own change (#83).
"""

import asyncio
import logging

from livekit.agents import (
    AgentServer,
    AutoSubscribe,
    JobContext,
    WorkerPermissions,
    cli,
)

from irya_ai.config import Settings, get_settings
from irya_ai.stt.elice import EliceSttClient, SttError, build_client
from irya_ai.stt.rtc_bridge import RoomTranscriber, session_id_from_room
from irya_ai.stt.stream import silent_probe

logger = logging.getLogger(__name__)


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

    async def transcribe_participant(_ctx: JobContext, participant) -> None:
        await transcriber.transcribe_participant(participant)

    # Register before connect so existing and later participants both get one
    # long-lived callback. The callbacks wait until t=0 is initialized.
    ctx.add_participant_entrypoint(transcribe_participant)
    warm_up = asyncio.create_task(_warm_up(client), name="stt-warm-up")
    ctx.add_shutdown_callback(lambda: _cancel(warm_up))
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    transcriber.initialize_origin(ctx.room.remote_participants.values())


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
