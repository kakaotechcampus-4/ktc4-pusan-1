from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
    }


def test_health_is_outside_api_prefix():
    """LB 가 부르는 경로라 버전 prefix 아래로 내려가면 안 된다."""
    assert client.get("/api/v1/health").status_code == 404
