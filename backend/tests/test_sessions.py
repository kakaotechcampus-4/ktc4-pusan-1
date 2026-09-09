"""세션 상태 · 입장 — 명세 `면접`·`진입` 카테고리."""

from fastapi.testclient import TestClient

from tests.conftest import FakeMedia

# ── 상태 조회 ────────────────────────────────────────────


def test_get_session(client: TestClient, session_id: str):
    response = client.get(f"/api/v1/sessions/{session_id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "sessionId",
        "interviewId",
        "status",
        "startedAt",
        "endedAt",
    }
    assert body["sessionId"] == session_id
    assert body["status"] == "WAITING"
    assert body["startedAt"] is None
    assert body["endedAt"] is None


def test_get_unknown_session(client: TestClient):
    response = client.get("/api/v1/sessions/ses_nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


# ── 입장 ────────────────────────────────────────────────


def test_join_returns_livekit_connection_info(client: TestClient, session_id: str):
    response = client.post(f"/api/v1/sessions/{session_id}/join", json={})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"sessionId", "livekitUrl", "token", "roomName"}
    assert body["sessionId"] == session_id
    assert body["roomName"] == f"interview_{session_id}"
    assert body["token"]


def test_join_defaults_to_candidate(client: TestClient, session_id: str):
    """명세 Request Body 예시가 CANDIDATE 다."""
    body = client.post(f"/api/v1/sessions/{session_id}/join", json={}).json()
    with_role = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"role": "CANDIDATE"}
    ).json()

    assert body["token"] == with_role["token"]


def test_join_as_interviewer(client: TestClient, session_id: str):
    response = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"role": "INTERVIEWER"}
    )

    assert response.status_code == 200


def test_join_rejects_unknown_role(client: TestClient, session_id: str):
    response = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"role": "admin"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_join_is_repeatable(client: TestClient, session_id: str):
    """토큰은 접속 시점에만 검증되므로 재입장은 다시 발급받으면 된다."""
    path = f"/api/v1/sessions/{session_id}/join"

    assert client.post(path, json={}).status_code == 200
    assert client.post(path, json={}).status_code == 200


def test_join_rejected_when_room_is_full(
    client: TestClient, session_id: str, media: FakeMedia
):
    media.participants = 2

    response = client.post(f"/api/v1/sessions/{session_id}/join", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROOM_FULL"


def test_join_rejected_after_end(client: TestClient, session_id: str):
    client.post(f"/api/v1/sessions/{session_id}/end")

    response = client.post(f"/api/v1/sessions/{session_id}/join", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SESSION_ENDED"


def test_join_unknown_session(client: TestClient):
    response = client.post("/api/v1/sessions/ses_nope/join", json={})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


# ── 시작 ────────────────────────────────────────────────


def test_start(client: TestClient, session_id: str):
    response = client.post(f"/api/v1/sessions/{session_id}/start")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"sessionId", "status", "startedAt"}
    assert body["status"] == "INTERVIEWING"
    assert body["startedAt"]


def test_start_twice_is_conflict(client: TestClient, session_id: str):
    """명세의 409 `현재 상태에서 시작할 수 없음`."""
    path = f"/api/v1/sessions/{session_id}/start"
    client.post(path)

    response = client.post(path)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_SESSION_STATE"


def test_start_after_end_is_conflict(client: TestClient, session_id: str):
    client.post(f"/api/v1/sessions/{session_id}/end")

    response = client.post(f"/api/v1/sessions/{session_id}/start")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_SESSION_STATE"


def test_start_unknown_session(client: TestClient):
    response = client.post("/api/v1/sessions/ses_nope/start")

    assert response.status_code == 404


# ── 종료 ────────────────────────────────────────────────


def test_end_records_time_and_closes_room(
    client: TestClient, session_id: str, media: FakeMedia
):
    response = client.post(f"/api/v1/sessions/{session_id}/end")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"sessionId", "status", "endedAt"}
    assert body["status"] == "ENDED"
    assert body["endedAt"]
    # 참가자가 남아 있어도 방을 닫아 끊는다.
    assert media.closed == [f"interview_{session_id}"]


def test_end_twice_is_conflict(client: TestClient, session_id: str, media: FakeMedia):
    """명세의 409 `현재 상태에서 종료할 수 없음`."""
    path = f"/api/v1/sessions/{session_id}/end"
    client.post(path)

    response = client.post(path)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_SESSION_STATE"
    # 두 번째 호출은 방을 다시 닫지 않는다.
    assert media.closed == [f"interview_{session_id}"]


def test_end_before_start_is_allowed(client: TestClient, session_id: str):
    """면접 시작 전 취소. WAITING -> ENDED 로 바로 간다."""
    response = client.post(f"/api/v1/sessions/{session_id}/end")

    assert response.status_code == 200
    assert response.json()["status"] == "ENDED"


def test_end_unknown_session(client: TestClient):
    response = client.post("/api/v1/sessions/ses_nope/end")

    assert response.status_code == 404
