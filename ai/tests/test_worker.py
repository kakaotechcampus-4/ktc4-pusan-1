"""The room job: what it refuses, what it wires, and the process boundary."""

import asyncio
import pickle
from types import SimpleNamespace

import httpx
import pytest

from irya_ai import worker
from irya_ai.stt.elice import EliceSttClient, SttError
from irya_ai.stt.rtc_bridge import RoomTranscriber
from irya_ai.worker import transcribe_room


class FakeJobContext:
    """The slice of ``JobContext`` the entrypoint touches."""

    def __init__(self, room_name: str) -> None:
        self.room = SimpleNamespace(name=room_name, remote_participants={})
        self.log_context_fields: dict = {}
        self.shutdown_reasons: list[str] = []
        self.entrypoints: list = []
        self.shutdown_callbacks: list = []
        self.connected_with: list = []

    def shutdown(self, reason: str = "user requested") -> None:
        self.shutdown_reasons.append(reason)

    def add_participant_entrypoint(self, fnc) -> None:
        self.entrypoints.append(fnc)

    def add_shutdown_callback(self, fnc) -> None:
        self.shutdown_callbacks.append(fnc)

    async def connect(self, **kwargs) -> None:
        self.connected_with.append(kwargs)


def probe_client() -> EliceSttClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "_result": {"status": "ok"},
                "transcript": {"text": "", "chunks": []},
            },
        )

    return EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid", transport=httpx.MockTransport(handler)
        ),
        retries=0,
        backoff_seconds=0.0,
    )


async def test_a_room_outside_the_naming_rule_is_left_alone(monkeypatch) -> None:
    ctx = FakeJobContext("demo_ses_123")
    monkeypatch.setattr(
        worker, "build_client", lambda settings: pytest.fail("no client expected")
    )

    await transcribe_room(ctx)  # type: ignore[arg-type]

    assert ctx.shutdown_reasons == ["unsupported room"]
    assert ctx.connected_with == []


async def test_an_unconfigured_stt_leaves_the_room_rather_than_hearing_nothing(
    monkeypatch,
) -> None:
    ctx = FakeJobContext("interview_ses_123")

    def refuse(settings):
        raise SttError("ELICE_STT_BASE_URL_NOT_SET")

    monkeypatch.setattr(worker, "build_client", refuse)

    await transcribe_room(ctx)  # type: ignore[arg-type]

    assert ctx.shutdown_reasons == ["stt not configured"]
    assert ctx.connected_with == []
    assert ctx.log_context_fields == {
        "room": "interview_ses_123",
        "session_id": "ses_123",
    }


async def test_a_room_job_wires_one_transcriber_and_connects_audio_only(
    monkeypatch,
) -> None:
    ctx = FakeJobContext("interview_ses_123")
    client = probe_client()
    monkeypatch.setattr(worker, "build_client", lambda settings: client)
    built: list[RoomTranscriber] = []
    original = worker.RoomTranscriber

    def capture(**kwargs) -> RoomTranscriber:
        built.append(original(**kwargs))
        return built[-1]

    monkeypatch.setattr(worker, "RoomTranscriber", capture)

    await transcribe_room(ctx)  # type: ignore[arg-type]

    assert ctx.shutdown_reasons == []
    assert len(ctx.entrypoints) == 1, "one long-lived callback per participant"
    assert [kw["auto_subscribe"].name for kw in ctx.connected_with] == ["AUDIO_ONLY"]
    assert len(built) == 1
    assert built[0].session_id == "ses_123"
    assert built[0].client is client
    # The HTTP client and the warm-up both go when the job does.
    assert len(ctx.shutdown_callbacks) == 2
    for callback in ctx.shutdown_callbacks:
        await callback()
    await asyncio.sleep(0)


def test_room_entrypoint_can_cross_the_worker_process_boundary() -> None:
    """AgentServer uses multiprocessing ``spawn``/``forkserver`` in production."""

    assert pickle.loads(pickle.dumps(transcribe_room)) is transcribe_room
