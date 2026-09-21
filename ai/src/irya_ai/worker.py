"""IRYA LiveKit STT worker.

Run locally with ``uv run python -m irya_ai.worker dev`` and in production
with ``python -m irya_ai.worker start``. The worker is unnamed on purpose:
the current single-product LiveKit deployment automatically dispatches it to
new rooms. Explicit backend dispatch can replace that when more agent types
share the server.
"""

import logging

from livekit.agents import (
    AgentServer,
    AutoSubscribe,
    JobContext,
    WorkerPermissions,
    cli,
)

from irya_ai.config import Settings, get_settings
from irya_ai.stt.cartesia import build_stt
from irya_ai.stt.rtc_bridge import RoomTranscriber, session_id_from_room

logger = logging.getLogger(__name__)


async def transcribe_room(ctx: JobContext) -> None:
    """Run one isolated STT job for one IRYA room."""

    session_id = session_id_from_room(ctx.room.name)
    if session_id is None:
        logger.warning("ignoring room outside IRYA naming rule room=%s", ctx.room.name)
        ctx.shutdown("unsupported room")
        return

    settings = get_settings()
    ctx.log_context_fields = {"room": ctx.room.name, "session_id": session_id}
    transcriber = RoomTranscriber(
        room=ctx.room,
        session_id=session_id,
        stt=build_stt(settings),
    )

    async def transcribe_participant(_ctx: JobContext, participant) -> None:
        await transcriber.transcribe_participant(participant)

    # Register before connect so existing and later participants both get one
    # long-lived callback. The callbacks wait until t=0 is initialized.
    ctx.add_participant_entrypoint(transcribe_participant)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    transcriber.initialize_origin(ctx.room.remote_participants.values())


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
