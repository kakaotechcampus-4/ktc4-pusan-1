"""카카오 로그인 (#118)."""

import io
import json
from datetime import timedelta
from urllib.error import HTTPError, URLError

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core import auth
from app.core.errors import ApiError, ErrorCode
from app.domain.models import utcnow
from app.services import kakao as kakao_module
from app.services.kakao import KakaoClient, KakaoProfile
from tests.conftest import FakeKakao


def _login(client: TestClient, code: str = "code_abc") -> dict:
    response = client.post("/api/v1/auth/kakao", json={"code": code})
    assert response.status_code == 200, response.text
    return response.json()


def _me(client: TestClient, token: str):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


def test_login_returns_token_that_opens_me(client: TestClient, kakao: FakeKakao):
    body = _login(client)

    assert kakao.codes == ["code_abc"]
    assert body["user"]["nickname"] == "김면접"
    assert body["user"]["profileImageUrl"] == "https://k.kakao/p.jpg"

    me = _me(client, body["accessToken"])
    assert me.status_code == 200
    assert me.json() == body["user"]


def test_second_login_is_same_user_with_fresh_profile(
    client: TestClient, kakao: FakeKakao
):
    first = _login(client)["user"]
    kakao.profile = KakaoProfile(kakao_id=4242, nickname="새닉", profile_image_url=None)

    second = _login(client, "code_def")["user"]

    assert second["id"] == first["id"]
    assert second["nickname"] == "새닉"
    assert second["profileImageUrl"] is None


@pytest.mark.parametrize(
    ("error", "status", "retryable"),
    [
        (kakao_module._auth_failed(), 401, False),  # pyright: ignore[reportPrivateUsage]
        (kakao_module._unavailable(), 502, True),  # pyright: ignore[reportPrivateUsage]
    ],
)
def test_kakao_failure_is_passed_through(
    client: TestClient, kakao: FakeKakao, error: ApiError, status: int, retryable: bool
):
    kakao.error = error

    response = client.post("/api/v1/auth/kakao", json={"code": "x"})

    assert response.status_code == status
    assert response.json()["error"]["code"] == error.code
    assert response.json()["error"]["retryable"] is retryable


def test_empty_code_is_rejected(client: TestClient):
    response = client.post("/api/v1/auth/kakao", json={"code": ""})

    assert response.status_code == 422


def _forged(**overrides) -> str:
    claims = {"sub": "usr_x", "exp": utcnow() + timedelta(days=1)} | overrides
    return jwt.encode(claims, "not-our-secret-" * 4, algorithm="HS256")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer garbage"},
        {"Authorization": f"Bearer {_forged()}"},
    ],
)
def test_me_without_valid_token_is_401(client: TestClient, headers: dict):
    response = client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHORIZED


def test_expired_token_is_401(client: TestClient):
    user_id = _login(client)["user"]["id"]
    expired = jwt.encode(
        {"sub": user_id, "exp": utcnow() - timedelta(seconds=1)},
        auth._secret,  # pyright: ignore[reportPrivateUsage]
        algorithm="HS256",
    )

    assert _me(client, expired).status_code == 401


def test_token_for_unknown_user_is_401(client: TestClient):
    assert _me(client, auth.issue_token("usr_gone")).status_code == 401


# ── 실제 클라이언트의 실패 분류 ─────────────────────────


def _http_error(code: int) -> HTTPError:
    body = io.BytesIO(json.dumps({"error_code": "KOE320"}).encode())
    return HTTPError("https://kauth.kakao.com", code, "x", {}, body)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (_http_error(400), ErrorCode.KAKAO_AUTH_FAILED),
        (_http_error(401), ErrorCode.KAKAO_AUTH_FAILED),
        (_http_error(503), ErrorCode.KAKAO_UNAVAILABLE),
        (URLError("dns"), ErrorCode.KAKAO_UNAVAILABLE),
        (TimeoutError(), ErrorCode.KAKAO_UNAVAILABLE),
    ],
)
def test_client_maps_kakao_failures(
    monkeypatch: pytest.MonkeyPatch, raised: Exception, expected: ErrorCode
):
    def fail(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr(kakao_module, "urlopen", fail)

    with pytest.raises(ApiError) as caught:
        KakaoClient().login("code")

    assert caught.value.code == expected


def test_client_reads_profile(monkeypatch: pytest.MonkeyPatch):
    replies = iter(
        [
            {"access_token": "kakao_tok"},
            {"id": 123, "kakao_account": {"profile": {"nickname": "김"}}},
        ]
    )
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(request)
        return io.BytesIO(json.dumps(next(replies)).encode())

    monkeypatch.setattr(kakao_module, "urlopen", fake_urlopen)

    profile = KakaoClient().login("code")

    assert profile == KakaoProfile(kakao_id=123, nickname="김", profile_image_url=None)
    assert sent[1].get_header("Authorization") == "Bearer kakao_tok"
