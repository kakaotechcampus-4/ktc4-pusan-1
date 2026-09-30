"""The room job: what it refuses, what it wires, and the process boundary."""

import asyncio
import pickle
from types import SimpleNamespace

import httpx
import pytest

from irya_ai import worker
from irya_ai.config import Settings
from irya_ai.openai_suggestions import OpenAISuggestionGenerator
from irya_ai.sinks import FanOutSink
from irya_ai.stt.elice import EliceSttClient, SttError
from irya_ai.stt.rtc_bridge import LiveKitTextSink, RoomTranscriber
from irya_ai.suggestion_runner import SuggestionRunner
from irya_ai.suggestions import ExtractiveSuggestionGenerator
from irya_ai.worker import build_suggestion_generator, transcribe_room


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


def settings_for(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def captured_transcribers(monkeypatch) -> list[RoomTranscriber]:
    built: list[RoomTranscriber] = []
    original = worker.RoomTranscriber

    def capture(**kwargs) -> RoomTranscriber:
        built.append(original(**kwargs))
        return built[-1]

    monkeypatch.setattr(worker, "RoomTranscriber", capture)
    return built


async def test_a_room_job_wires_one_transcriber_and_connects_audio_only(
    monkeypatch,
) -> None:
    ctx = FakeJobContext("interview_ses_123")
    client = probe_client()
    monkeypatch.setattr(worker, "build_client", lambda settings: client)
    monkeypatch.setattr(worker, "get_settings", settings_for)
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


async def test_without_a_backend_the_caption_is_the_only_consumer(
    monkeypatch,
) -> None:
    ctx = FakeJobContext("interview_ses_123")
    monkeypatch.setattr(worker, "build_client", lambda settings: probe_client())
    monkeypatch.setattr(
        worker, "get_settings", lambda: settings_for(backend_base_url="")
    )
    built = captured_transcribers(monkeypatch)

    await transcribe_room(ctx)  # type: ignore[arg-type]

    assert ctx.shutdown_reasons == []
    (fan_out,) = built[0].sinks
    assert isinstance(fan_out, FanOutSink)
    assert fan_out.sinks == [built[0].caption]
    assert len(ctx.shutdown_callbacks) == 2, "nothing extra to take down"


async def test_with_a_backend_the_runner_joins_the_fan_out_and_stops_with_the_job(
    monkeypatch,
) -> None:
    ctx = FakeJobContext("interview_ses_123")
    monkeypatch.setattr(worker, "build_client", lambda settings: probe_client())
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: settings_for(backend_base_url="https://backend.invalid"),
    )
    built = captured_transcribers(monkeypatch)

    await transcribe_room(ctx)  # type: ignore[arg-type]

    (fan_out,) = built[0].sinks
    assert isinstance(fan_out, FanOutSink)
    caption, runner = fan_out.sinks
    assert isinstance(caption, LiveKitTextSink), "the interviewer sees words first"
    assert isinstance(runner, SuggestionRunner)
    assert runner.session_id == "ses_123"
    assert runner.running, "started once the room is connected"
    assert isinstance(runner.agent.generator, ExtractiveSuggestionGenerator), (
        "no LLM configured: the baseline, not nothing"
    )

    # STT client, the suggestion loop, the warm-up: all go when the job does.
    assert len(ctx.shutdown_callbacks) == 3
    for callback in ctx.shutdown_callbacks:
        await callback()
    assert not runner.running


@pytest.mark.parametrize("backend", ["", "https://backend.invalid"])
@pytest.mark.parametrize("llm", ["", "https://llm.invalid"])
async def test_the_worker_starts_in_every_backend_and_llm_combination(
    monkeypatch, backend: str, llm: str
) -> None:
    """Missing wiring narrows what the worker does; it never keeps it out."""

    ctx = FakeJobContext("interview_ses_123")
    monkeypatch.setattr(worker, "build_client", lambda settings: probe_client())
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: settings_for(
            backend_base_url=backend,
            llm_base_url=llm,
            llm_api_key="test-key" if llm else "",
        ),
    )
    captured_transcribers(monkeypatch)

    await transcribe_room(ctx)  # type: ignore[arg-type]

    assert ctx.shutdown_reasons == []
    assert len(ctx.connected_with) == 1
    for callback in ctx.shutdown_callbacks:
        await callback()


def test_the_project_llm_is_used_only_when_both_its_values_are_set() -> None:
    generator, client = build_suggestion_generator(
        settings_for(llm_base_url="https://llm.invalid", llm_api_key="test-key")
    )
    assert isinstance(generator, OpenAISuggestionGenerator)
    assert client is not None
    assert generator.model == settings_for().llm_model
    asyncio.run(client.close())

    for partial in (
        settings_for(llm_base_url="https://llm.invalid", llm_api_key=""),
        settings_for(llm_base_url="", llm_api_key="test-key"),
    ):
        generator, client = build_suggestion_generator(partial)
        assert isinstance(generator, ExtractiveSuggestionGenerator)
        assert client is None


def test_room_entrypoint_can_cross_the_worker_process_boundary() -> None:
    """AgentServer uses multiprocessing ``spawn``/``forkserver`` in production."""

    assert pickle.loads(pickle.dumps(transcribe_room)) is transcribe_room
