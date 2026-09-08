"""공통 에러 응답 포맷 — 테크스펙 §2."""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_unknown_path_uses_common_error_format():
    response = client.get("/no-such-path")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "retryable"}
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["retryable"] is False


def test_error_body_has_no_fastapi_detail_key():
    """FastAPI 기본 응답은 최상위 `detail` 이다. 규격과 다르므로 남아 있으면 안 된다."""
    assert "detail" not in client.get("/no-such-path").json()


def test_cors_allows_frontend_origin():
    origin = settings.cors_origin_list[0]
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_rejects_unknown_origin():
    response = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers
