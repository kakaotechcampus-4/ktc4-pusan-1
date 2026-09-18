"""The Backend client: where it sends, what it retries, and what it hides."""

import json

import httpx
import pytest

from irya_ai.backend import (
    BackendClient,
    BackendError,
    build_client,
    build_http_client,
    path_segment,
)
from irya_ai.config import Settings
from irya_ai.schemas.base import CamelModel
from irya_ai.schemas.wire import SuggestionPayload
from irya_ai.stt.http_logging import clear_protected_hosts, protected_hosts

# ``send`` is route- and payload-agnostic: every ``/internal/v1`` call is a
# path plus a wire model, and these tests are about how an answer is
# classified, not about what any one route promises. So the payload is a
# stand-in rather than a real contract model - a change to ``SuggestionPayload``
# must not turn a retry test red - and the route is the suggestion one because
# that is the only route on this client. Transcripts left HTTP for the
# WebSocket in ``irya_ai.transcripts``, which has its own tests; what
# ``post_suggestion`` itself promises is at the bottom of this file.
ROUTE = "/internal/v1/sessions/ses_123/suggestions"


class Payload(CamelModel):
    """Two fields, one of them renamed, which is all ``by_alias`` needs to show."""

    utterance_id: str
    text: str


PAYLOAD = Payload(
    utterance_id="utt_001",
    text="인턴 당시 React Native로 지도 기능을 개발했습니다.",
)


def client_for(handler, **kwargs) -> BackendClient:
    return BackendClient(
        httpx.AsyncClient(
            base_url="https://backend.invalid",
            transport=httpx.MockTransport(handler),
        ),
        backoff_seconds=0.0,
        **kwargs,
    )


async def test_a_payload_goes_to_the_route_it_was_given_in_camel_case() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    await client_for(handler).send("POST", ROUTE, PAYLOAD)

    assert seen[0].method == "POST"
    assert seen[0].url.path == ROUTE
    assert json.loads(seen[0].content) == {
        "utteranceId": "utt_001",
        "text": "인턴 당시 React Native로 지도 기능을 개발했습니다.",
    }


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "BACKEND_AUTH_FAILED", False),
        (403, "BACKEND_AUTH_FAILED", False),
        (400, "BACKEND_CLIENT_ERROR", False),
        (404, "BACKEND_CLIENT_ERROR", False),
        (422, "BACKEND_CLIENT_ERROR", False),
        (429, "BACKEND_REQUEST_FAILED", True),
        (500, "BACKEND_REQUEST_FAILED", True),
        (503, "BACKEND_REQUEST_FAILED", True),
    ],
)
async def test_a_status_becomes_a_typed_error(
    status: int, code: str, retryable: bool
) -> None:
    with pytest.raises(BackendError) as caught:
        await client_for(lambda r: httpx.Response(status)).send("POST", ROUTE, PAYLOAD)

    assert caught.value.code == code
    assert caught.value.retryable is retryable


async def test_only_a_failure_that_could_answer_differently_is_retried() -> None:
    """A 422 is Backend saying the body is wrong; sending it twice more is noise."""

    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(422)

    with pytest.raises(BackendError):
        await client_for(handler).send("POST", ROUTE, PAYLOAD)

    assert len(attempts) == 1


async def test_a_retryable_failure_is_tried_again_and_can_succeed() -> None:
    answers = iter([503, 503, 201])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(answers))

    await client_for(handler).send("POST", ROUTE, PAYLOAD)


async def test_it_gives_up_after_the_last_attempt() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503)

    with pytest.raises(BackendError, match="BACKEND_REQUEST_FAILED"):
        await client_for(handler, retries=2).send("POST", ROUTE, PAYLOAD)

    assert len(attempts) == 3


async def test_a_transport_failure_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(BackendError) as caught:
        await client_for(handler).send("POST", ROUTE, PAYLOAD)

    assert caught.value.retryable is True


async def test_a_cancelled_request_is_not_reported_as_a_backend_failure() -> None:
    """Shutting the Agent down must not look like Backend rejecting a call."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        await client_for(handler).send("POST", ROUTE, PAYLOAD)


@pytest.mark.parametrize("session_id", ["", "   ", "ses/../other", "..", "a/b"])
def test_a_session_id_that_would_rewrite_the_path_is_refused(session_id: str) -> None:
    """Both transports build their path with this, so it is tested on its own."""

    with pytest.raises(BackendError, match="BACKEND_INVALID_SESSION_ID"):
        path_segment(session_id)


def test_a_session_id_is_taken_as_given_once_it_is_safe() -> None:
    assert path_segment("  ses_123  ") == "ses_123"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [({"retries": -1}, "retries"), ({"backoff_seconds": -1.0}, "backoff")],
)
def test_a_client_refuses_settings_it_could_not_act_on(
    kwargs: dict, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        BackendClient(
            httpx.AsyncClient(
                base_url="https://backend.invalid",
                transport=httpx.MockTransport(lambda r: httpx.Response(200)),
            ),
            **kwargs,
        )


def test_build_http_client_refuses_an_unconfigured_backend() -> None:
    with pytest.raises(BackendError, match="BACKEND_BASE_URL"):
        build_http_client(Settings(_env_file=None))


def test_build_client_carries_settings_onto_the_client() -> None:
    settings = Settings(
        _env_file=None,
        backend_base_url="https://backend.invalid/",
        backend_api_key="unit-test-token",
    )

    client = build_client(
        settings, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )

    assert str(client.client.base_url) == "https://backend.invalid"
    assert client.client.headers["authorization"] == "Bearer unit-test-token"


def test_an_unset_key_sends_no_authorization_header_at_all() -> None:
    """An empty bearer reads as a client that believes it authenticated."""

    settings = Settings(_env_file=None, backend_base_url="https://backend.invalid")

    client = build_client(
        settings, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )

    assert "authorization" not in client.client.headers


def test_the_backend_host_is_registered_for_log_redaction() -> None:
    clear_protected_hosts()
    try:
        client_for(lambda r: httpx.Response(201))
        assert "backend.invalid" in protected_hosts()
    finally:
        clear_protected_hosts()


SUGGESTION = SuggestionPayload(
    suggestion_id="sug_001",
    type="FOLLOW_UP",
    content="말씀하신 캐시 무효화 전략을 어떻게 검증했는지 질문해보세요.",
    evidence_utterance_ids=["utt_001", "utt_002"],
)


async def test_a_suggestion_goes_to_the_agreed_route_with_the_agreed_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    await client_for(handler).post_suggestion("ses_123", SUGGESTION)

    assert seen[0].method == "POST"
    assert seen[0].url.path == "/internal/v1/sessions/ses_123/suggestions"
    assert json.loads(seen[0].content) == {
        "suggestionId": "sug_001",
        "type": "FOLLOW_UP",
        "content": "말씀하신 캐시 무효화 전략을 어떻게 검증했는지 질문해보세요.",
        "evidenceUtteranceIds": ["utt_001", "utt_002"],
    }


async def test_a_suggestion_fails_the_way_every_send_does() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(BackendError) as info:
        await client_for(handler).post_suggestion("ses_123", SUGGESTION)

    assert info.value.code == "BACKEND_REQUEST_FAILED"
    assert info.value.retryable is True


async def test_a_suggestion_route_refuses_a_session_id_that_rewrites_the_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not send")

    with pytest.raises(BackendError) as info:
        await client_for(handler).post_suggestion("../../admin", SUGGESTION)

    assert info.value.code == "BACKEND_INVALID_SESSION_ID"
