"""면접 · 세션 생성 — 명세 `면접` 카테고리."""

from fastapi.testclient import TestClient

from app.domain.models import User
from tests.conftest import FakeMedia


def test_create_interview(client: TestClient, owner: User):
    """주인은 토큰의 사용자다. 본문의 `interviewerId` 는 무시한다 (#130)."""
    response = client.post("/api/v1/interviews", json={"interviewerId": "user_123"})

    assert response.status_code == 201
    body = response.json()
    assert body["interviewId"].startswith("int_")
    assert body["interviewerId"] == owner.id
    assert body["candidateName"] is None
    assert body["createdAt"]
    assert set(body) == {"interviewId", "interviewerId", "candidateName", "createdAt"}


def test_create_interview_accepts_candidate_name(client: TestClient):
    response = client.post(
        "/api/v1/interviews",
        json={"interviewerId": "user_123", "candidateName": "  김지원  "},
    )

    assert response.status_code == 201
    assert response.json()["candidateName"] == "김지원"


def test_create_interview_rejects_overlong_candidate_name(client: TestClient):
    """명세의 422 `요청값 검증 실패`."""
    response = client.post("/api/v1/interviews", json={"candidateName": "가" * 21})

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
        "candidateName",
        "status",
        "inviteUrl",
        "createdAt",
    }
    assert body["sessionId"].startswith("ses_")
    assert body["interviewId"] == interview["interviewId"]
    assert body["candidateName"] is None
    assert body["status"] == "WAITING"
    assert body["inviteUrl"].endswith(f"/interview/{body['sessionId']}")
    # LiveKit Room 을 미리 만들어야 max_participants 가 적용된다.
    assert media.rooms == [f"interview_{body['sessionId']}"]


def test_create_session_returns_candidate_name(client: TestClient):
    interview = client.post(
        "/api/v1/interviews",
        json={"interviewerId": "user_123", "candidateName": "김지원"},
    ).json()

    response = client.post(f"/api/v1/interviews/{interview['interviewId']}/sessions")

    assert response.status_code == 201
    assert response.json()["candidateName"] == "김지원"


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


# ── 내 면접 목록 (#144) ─────────────────────────────────


def test_list_is_mine_newest_first_with_latest_session(
    client: TestClient, other: dict[str, str]
):
    first = client.post("/api/v1/interviews", json={"candidateName": "가"}).json()
    second = client.post("/api/v1/interviews", json={"candidateName": "나"}).json()
    client.post("/api/v1/interviews", json={}, headers=other)
    client.post(f"/api/v1/interviews/{first['interviewId']}/sessions")
    latest = client.post(f"/api/v1/interviews/{first['interviewId']}/sessions").json()
    client.post(f"/api/v1/sessions/{latest['sessionId']}/start")

    response = client.get("/api/v1/interviews")

    assert response.status_code == 200
    items = response.json()
    assert [i["interviewId"] for i in items] == [
        second["interviewId"],
        first["interviewId"],
    ]
    assert items[0] == {
        "interviewId": second["interviewId"],
        "candidateName": "나",
        "createdAt": second["createdAt"],
        "latestSession": None,
    }
    session = items[1]["latestSession"]
    assert session["sessionId"] == latest["sessionId"]
    assert session["status"] == "INTERVIEWING"
    assert session["startedAt"] is not None
    assert session["endedAt"] is None


def test_list_is_empty_for_a_new_interviewer(client: TestClient):
    assert client.get("/api/v1/interviews").json() == []
