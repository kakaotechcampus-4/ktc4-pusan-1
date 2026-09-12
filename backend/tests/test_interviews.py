"""면접 · 세션 생성 — 명세 `면접` 카테고리."""

from fastapi.testclient import TestClient

from tests.conftest import FakeMedia


def test_create_interview(client: TestClient):
    response = client.post("/api/v1/interviews", json={"interviewerId": "user_123"})

    assert response.status_code == 201
    body = response.json()
    assert body["interviewId"].startswith("int_")
    assert body["interviewerId"] == "user_123"
    assert body["createdAt"]
    assert set(body) == {"interviewId", "interviewerId", "createdAt"}


def test_create_interview_rejects_empty_id(client: TestClient):
    """명세의 422 `요청값 검증 실패`."""
    response = client.post("/api/v1/interviews", json={"interviewerId": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_interview(client: TestClient):
    created = client.post(
        "/api/v1/interviews", json={"interviewerId": "user_123"}
    ).json()

    response = client.get(f"/api/v1/interviews/{created['interviewId']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_interview(client: TestClient):
    response = client.get("/api/v1/interviews/int_nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INTERVIEW_NOT_FOUND"


def test_create_session(client: TestClient, media: FakeMedia):
    interview = client.post(
        "/api/v1/interviews", json={"interviewerId": "user_123"}
    ).json()

    response = client.post(f"/api/v1/interviews/{interview['interviewId']}/sessions")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "sessionId",
        "interviewId",
        "status",
        "inviteUrl",
        "createdAt",
    }
    assert body["sessionId"].startswith("ses_")
    assert body["interviewId"] == interview["interviewId"]
    assert body["status"] == "WAITING"
    assert body["inviteUrl"].endswith(f"/interview/{body['sessionId']}")
    # LiveKit Room 을 미리 만들어야 max_participants 가 적용된다.
    assert media.rooms == [f"interview_{body['sessionId']}"]


def test_create_session_for_unknown_interview(client: TestClient, media: FakeMedia):
    response = client.post("/api/v1/interviews/int_nope/sessions")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INTERVIEW_NOT_FOUND"
    assert media.rooms == []


def test_interview_can_have_multiple_sessions(client: TestClient):
    """명세가 sessions 를 컬렉션으로 두었으므로 1:N 이다."""
    interview = client.post(
        "/api/v1/interviews", json={"interviewerId": "user_123"}
    ).json()
    path = f"/api/v1/interviews/{interview['interviewId']}/sessions"

    first = client.post(path).json()["sessionId"]
    second = client.post(path).json()["sessionId"]

    assert first != second
