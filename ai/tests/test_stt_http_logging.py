"""The deployment host, and whether the HTTP libraries can print it.

Every test here captures the root logger, because that is where an embedding
application attaches its handler and where ``httpx`` and ``httpcore`` records
arrive by propagation. Capturing the STT package's own logger instead is what
let this leak sit unnoticed: the records that carry the URL are not written by
this package.

Nothing here touches the network. ``MockTransport`` answers every request, so
``httpcore`` never runs - the records shaped like its are logged directly, at
the format strings the installed version uses.
"""

import asyncio
import io
import logging
import pathlib
import re

import httpcore
import httpx
import pytest

from irya_ai.config import Settings
from irya_ai.stt.elice import EliceSttClient, SttError, build_client
from irya_ai.stt.http_logging import (
    HTTP_CLIENT_LOGGERS,
    REDACTED_HOST,
    clear_protected_hosts,
    protect_host,
    protected_hosts,
)

HOST = "private-deployment.invalid"
UNRELATED = "public-service.invalid"
KEY = "canary-api-key-must-never-be-logged"
TRANSCRIPT = "canary-transcript-must-never-be-logged"
WAV = b"RIFF....WAVEfmt "


@pytest.fixture(autouse=True)
def _isolated_protection():
    """Start from no registrations, and leave the loggers as they were.

    Other modules construct clients, which registers their hosts for the rest
    of the process. Clearing on both sides keeps these assertions independent
    of test order.
    """

    clear_protected_hosts()
    yield
    clear_protected_hosts()


class Captured:
    """A handler on the root logger, and the text it collected."""

    def __init__(self, level: int) -> None:
        self.buffer = io.StringIO()
        self.handler = logging.StreamHandler(self.buffer)
        self.level = level

    def __enter__(self) -> "Captured":
        root = logging.getLogger()
        self._previous = root.level
        root.setLevel(self.level)
        root.addHandler(self.handler)
        return self

    def __exit__(self, *exc_info) -> None:
        root = logging.getLogger()
        root.removeHandler(self.handler)
        root.setLevel(self._previous)

    @property
    def text(self) -> str:
        return self.buffer.getvalue()


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "_result": {"status": "ok"},
            "transcript": {
                "text": TRANSCRIPT,
                "chunks": [{"timestamp": [0.0, 1.0], "text": TRANSCRIPT}],
            },
        },
    )


def deployment_client(handler=ok, *, host: str = HOST) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"https://{host}",
        headers={"Authorization": f"Bearer {KEY}"},
        transport=httpx.MockTransport(handler),
    )


async def test_a_successful_request_keeps_the_host_out_of_the_root_log() -> None:
    with Captured(logging.INFO) as log:
        async with deployment_client() as http:
            await EliceSttClient(http, retries=0).transcribe(WAV)

    assert HOST not in log.text
    # Redacted, not silenced: the request is still there to be read.
    assert "HTTP Request: POST" in log.text
    assert REDACTED_HOST in log.text
    assert "/v1/audio/transcriptions" in log.text
    assert "200 OK" in log.text


async def test_a_failed_request_keeps_the_host_out_of_the_root_log() -> None:
    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": TRANSCRIPT})

    with Captured(logging.DEBUG) as log:
        async with deployment_client(server_error) as http:
            client = EliceSttClient(http, retries=0)
            with pytest.raises(SttError):
                await asyncio.wait_for(client.transcribe(WAV), timeout=2)

    assert HOST not in log.text
    assert REDACTED_HOST in log.text
    assert "500" in log.text


async def test_the_key_and_the_response_body_never_reach_the_log() -> None:
    with Captured(logging.DEBUG) as log:
        async with deployment_client() as http:
            await EliceSttClient(http, retries=0).transcribe(WAV)

    assert KEY not in log.text
    assert TRANSCRIPT not in log.text
    assert HOST not in log.text


async def test_a_handler_on_the_dependency_logger_sees_the_redacted_record() -> None:
    """Not only the root: the record itself is rewritten, wherever it lands."""

    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    httpx_logger = logging.getLogger("httpx")
    previous = httpx_logger.level
    httpx_logger.setLevel(logging.INFO)
    httpx_logger.addHandler(handler)
    try:
        async with deployment_client() as http:
            await EliceSttClient(http, retries=0).transcribe(WAV)
    finally:
        httpx_logger.removeHandler(handler)
        httpx_logger.setLevel(previous)

    assert HOST not in buffer.getvalue()
    assert REDACTED_HOST in buffer.getvalue()


async def test_httpcore_debug_records_are_redacted_too() -> None:
    """The connection records, which name the host at DEBUG rather than INFO.

    ``MockTransport`` means real ``httpcore`` never runs in this suite, so
    these are its own format strings and arguments, logged to its own loggers.
    """

    protect_host(f"https://{HOST}")
    connection = logging.getLogger("httpcore.connection")

    with Captured(logging.DEBUG) as log:
        connection.debug(
            "connect_tcp.started host=%r port=%r local_address=%r timeout=%r "
            "socket_options=%r",
            HOST,
            443,
            None,
            5.0,
            None,
        )
        connection.debug(
            "start_tls.started ssl_context=%r server_hostname=%r timeout=%r",
            "<ssl.SSLContext>",
            HOST,
            5.0,
        )

    assert HOST not in log.text
    assert log.text.count(REDACTED_HOST) == 2
    # The shape of the record survives; only the host is gone.
    assert "connect_tcp.started" in log.text
    assert "port=443" in log.text


async def test_a_concurrent_unrelated_request_keeps_its_ordinary_log() -> None:
    def anything(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with Captured(logging.INFO) as log:
        async with (
            deployment_client() as http,
            httpx.AsyncClient(
                base_url=f"https://{UNRELATED}",
                transport=httpx.MockTransport(anything),
            ) as other,
        ):
            client = EliceSttClient(http, retries=0)
            await asyncio.wait_for(
                asyncio.gather(client.transcribe(WAV), other.get("/health")),
                timeout=2,
            )

    assert HOST not in log.text
    # Untouched, host and all: this filter protects one endpoint, it does not
    # take the application's HTTP logging away.
    assert f"https://{UNRELATED}/health" in log.text


async def test_protection_is_scoped_to_the_http_client_loggers() -> None:
    """Stated as a test because it is the boundary of what this can promise.

    A caller that writes the URL from its own logger is writing its own
    record, and this does not reach into it.
    """

    protect_host(f"https://{HOST}")

    with Captured(logging.INFO) as log:
        logging.getLogger("some.application.module").info("posting to %s", HOST)

    assert HOST in log.text


async def test_cancelling_a_request_leaks_nothing() -> None:
    started = asyncio.Event()

    async def never_answers(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    with Captured(logging.DEBUG) as log:
        async with deployment_client(never_answers) as http:
            client = EliceSttClient(http, retries=0)
            task = asyncio.create_task(client.transcribe(WAV))
            await asyncio.wait_for(started.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)

        # A request torn down mid-flight logs nothing itself; what matters is
        # that it leaves the protection standing for the requests after it.
        assert protected_hosts() == frozenset({HOST})
        logging.getLogger("httpx").info("HTTP Request: POST https://%s/x", HOST)

    assert HOST not in log.text
    assert REDACTED_HOST in log.text


async def test_an_unformattable_record_is_dropped_when_it_names_the_host() -> None:
    """``logging`` prints the raw msg and args to stderr when formatting fails.

    There is nothing to redact in place on a record like that, so it goes.
    """

    protect_host(f"https://{HOST}")

    with Captured(logging.DEBUG) as log:
        # One argument too few for the format string: ``getMessage`` raises.
        logging.getLogger("httpcore.connection").debug(
            "connect_tcp.started host=%r port=%d", HOST
        )

    assert log.text == ""


def test_registering_a_host_twice_does_not_stack_filters() -> None:
    before = {
        name: len(logging.getLogger(name).filters) for name in HTTP_CLIENT_LOGGERS
    }

    assert protect_host(f"https://{HOST}/v1") == HOST
    assert protect_host(f"https://{HOST}:8443/other") == HOST
    assert protect_host(HOST.upper()) == HOST

    assert protected_hosts() == frozenset({HOST})
    for name in HTTP_CLIENT_LOGGERS:
        assert len(logging.getLogger(name).filters) == before[name] + 1


def test_clearing_restores_the_loggers_and_the_redaction_stops() -> None:
    before = {
        name: list(logging.getLogger(name).filters) for name in HTTP_CLIENT_LOGGERS
    }

    protect_host(f"https://{HOST}")
    clear_protected_hosts()

    assert protected_hosts() == frozenset()
    for name in HTTP_CLIENT_LOGGERS:
        assert logging.getLogger(name).filters == before[name]

    with Captured(logging.INFO) as log:
        logging.getLogger("httpx").info("HTTP Request: POST https://%s/x", HOST)

    assert HOST in log.text


def test_a_client_with_no_base_url_registers_nothing() -> None:
    assert protect_host("") is None
    assert protect_host(httpx.URL("")) is None
    assert protected_hosts() == frozenset()

    # The empty host must never become a pattern: it would match everywhere
    # and redact every HTTP record in the process.
    with Captured(logging.INFO) as log:
        logging.getLogger("httpx").info("HTTP Request: GET https://%s/x", UNRELATED)

    assert f"https://{UNRELATED}/x" in log.text


def test_the_supported_entry_path_registers_the_configured_deployment() -> None:
    settings = Settings(
        _env_file=None,
        elice_stt_base_url=f"https://{HOST}/",
        elice_api_key=KEY,
    )

    build_client(settings, transport=httpx.MockTransport(ok))

    assert protected_hosts() == frozenset({HOST})


def test_a_bare_host_string_is_accepted() -> None:
    assert protect_host("deployment.invalid:8000") == "deployment.invalid"


def test_every_logger_the_installed_http_stack_writes_to_is_protected() -> None:
    """Catches a new logger name arriving with an upgrade of either package."""

    declared: set[str] = set()
    for package in (httpx, httpcore):
        for module in pathlib.Path(package.__file__).parent.rglob("*.py"):
            declared |= set(
                re.findall(
                    r'getLogger\(\s*["\']([^"\']+)["\']',
                    module.read_text(encoding="utf-8"),
                )
            )

    assert declared
    assert declared <= set(HTTP_CLIENT_LOGGERS)
