"""세션 상태 · 입장 — 명세 `면접`·`진입` 카테고리."""

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Session, SessionStatus
from app.domain.store import InMemoryStore
from tests.conftest import FakeMedia


def _consent(client: TestClient, session_id: str, **body: object):
    """지원자 동의. 동의가 없으면 지원자로 입장할 수 없다 (#245)."""
    return client.post(
        f"/api/v1/sessions/{session_id}/consent",
        json={"policyVersion": "2026-10-30", **body},
    )


# ── 상태 조회 ────────────────────────────────────────────


def test_get_session(client: TestClient, session_id: str):
    response = client.get(f"/api/v1/sessions/{session_id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "sessionId",
        "interviewId",
        "candidateName",
        "status",
        "startedAt",
        "endedAt",
        "transcriptOriginAt",
        "consentedAt",
    }
    assert body["sessionId"] == session_id
    assert body["candidateName"] is None
    assert body["status"] == "WAITING"
    assert body["startedAt"] is None
    assert body["endedAt"] is None
    # Webhook 이 오기 전까지는 비어 있다.
    assert body["transcriptOriginAt"] is None
    # 동의 전까지는 비어 있다 (#245).
    assert body["consentedAt"] is None


def test_get_unknown_session(client: TestClient):
    response = client.get("/api/v1/sessions/ses_nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


# ── 입장 ────────────────────────────────────────────────


def test_join_returns_livekit_connection_info(client: TestClient, session_id: str):
    _consent(client, session_id)

    response = client.post(f"/api/v1/sessions/{session_id}/join", json={})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "sessionId",
        "candidateName",
        "livekitUrl",
        "token",
        "roomName",
    }
    assert body["sessionId"] == session_id
    assert body["candidateName"] is None
    assert body["roomName"] == f"interview_{session_id}"
    assert body["token"]


def test_join_returns_candidate_name(client: TestClient):
    interview = client.post(
        "/api/v1/interviews",
        json={"candidateName": "김지원"},
    ).json()
    session = client.post(
        f"/api/v1/interviews/{interview['interviewId']}/sessions"
    ).json()

    response = client.post(
        f"/api/v1/sessions/{session['sessionId']}/join",
        json={"role": "INTERVIEWER"},
    )

    assert response.status_code == 200
    assert response.json()["candidateName"] == "김지원"


def test_join_defaults_to_candidate(client: TestClient, session_id: str):
    """명세 Request Body 예시가 CANDIDATE 다."""
    _consent(client, session_id)
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
    _consent(client, session_id)
    path = f"/api/v1/sessions/{session_id}/join"

    assert client.post(path, json={}).status_code == 200
    assert client.post(path, json={}).status_code == 200


def test_join_rejected_when_room_is_full(
    client: TestClient, session_id: str, media: FakeMedia
):
    _consent(client, session_id)
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


# ── 지원자 동의 ─────────────────────────────────────────


def test_consent_records_the_interview_candidate_name(client: TestClient):
    """지원자는 로그인하지 않는다. 면접에 적힌 이름을 동의 시점에 떠 둔다 (#245)."""
    interview = client.post(
        "/api/v1/interviews", json={"candidateName": "김지원"}
    ).json()
    session = client.post(
        f"/api/v1/interviews/{interview['interviewId']}/sessions"
    ).json()

    response = _consent(client, session["sessionId"])

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"sessionId", "candidateName", "policyVersion", "consentedAt"}
    assert body["candidateName"] == "김지원"
    assert body["policyVersion"] == "2026-10-30"
    assert body["consentedAt"]


def test_consent_ignores_a_blank_name(client: TestClient):
    """공백만 적은 이름은 안 적은 것으로 본다 — 면접에 적힌 이름으로 떨어진다."""
    interview = client.post(
        "/api/v1/interviews", json={"candidateName": "김지원"}
    ).json()
    session = client.post(
        f"/api/v1/interviews/{interview['interviewId']}/sessions"
    ).json()

    body = _consent(client, session["sessionId"], candidateName="   ").json()

    assert body["candidateName"] == "김지원"


def test_consent_prefers_the_name_the_candidate_typed(client: TestClient):
    interview = client.post(
        "/api/v1/interviews", json={"candidateName": "김지원"}
    ).json()
    session = client.post(
        f"/api/v1/interviews/{interview['interviewId']}/sessions"
    ).json()

    body = _consent(client, session["sessionId"], candidateName="김지원 본인").json()

    assert body["candidateName"] == "김지원 본인"


def test_consent_is_repeatable_and_keeps_the_first_record(
    client: TestClient, session_id: str
):
    """새로고침 · 중복 클릭에 기록이 흔들리면 안 된다."""
    first = _consent(client, session_id).json()

    again = client.post(
        f"/api/v1/sessions/{session_id}/consent",
        json={"policyVersion": "다른버전", "candidateName": "다른이름"},
    )

    assert again.status_code == 200
    assert again.json() == first


def test_consent_shows_up_in_session_state(client: TestClient, session_id: str):
    agreed_at = _consent(client, session_id).json()["consentedAt"]

    body = client.get(f"/api/v1/sessions/{session_id}").json()

    assert body["consentedAt"] == agreed_at


def test_consent_rejected_after_end(client: TestClient, session_id: str):
    client.post(f"/api/v1/sessions/{session_id}/end")

    response = _consent(client, session_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SESSION_ENDED"


def test_consent_unknown_session(client: TestClient):
    response = _consent(client, "ses_nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_consent_requires_a_policy_version(client: TestClient, session_id: str):
    response = client.post(f"/api/v1/sessions/{session_id}/consent", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_candidate_cannot_join_without_consent(client: TestClient, session_id: str):
    """토큰이 없으면 LiveKit 에 트랙을 못 올린다. 녹화 · 전사가 거기서 시작한다."""
    response = client.post(f"/api/v1/sessions/{session_id}/join", json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_consent_gate_runs_before_livekit(
    client: TestClient, session_id: str, media: FakeMedia
):
    """못 들어갈 요청으로 LiveKit 을 부르지 않는다 — 기존 권한 검사와 같은 원칙."""
    client.post(f"/api/v1/sessions/{session_id}/join", json={})

    assert media.counted == []


def test_interviewer_can_join_before_consent(client: TestClient, session_id: str):
    """면접관은 동의와 무관하게 들어간다. 지원자를 기다리는 화면이 먼저 필요하다."""
    response = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"role": "INTERVIEWER"}
    )

    assert response.status_code == 200


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


def test_start_losing_the_race_is_conflict(
    client: TestClient,
    session_id: str,
    store: InMemoryStore,
    monkeypatch: pytest.MonkeyPatch,
):
    """읽은 뒤 저장하기 전에 다른 요청이 먼저 시작한 경우도 409 다.

    상태 검사는 통과했는데 저장이 거절당하는 상황을 만든다.
    """
    monkeypatch.setattr(store, "save_session", lambda *a, **k: False)

    response = client.post(f"/api/v1/sessions/{session_id}/start")

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


def test_end_losing_the_race_keeps_the_start(
    client: TestClient,
    session_id: str,
    store: InMemoryStore,
    media: FakeMedia,
    monkeypatch: pytest.MonkeyPatch,
):
    """종료가 세션을 읽은 직후 시작이 먼저 저장된 경우 (#131).

    조건 없이 쓰면 읽어 둔 WAITING 세션으로 덮어, 면접관이 200 을 받은 시작이
    지워진다.
    """
    read = store.get_session

    def read_then_start(sid: str) -> Session | None:
        found = read(sid)
        late = read(sid)
        assert late is not None and late.start()
        store.save_session(late, expected_status=SessionStatus.WAITING)
        return found

    monkeypatch.setattr(store, "get_session", read_then_start)
    response = client.post(f"/api/v1/sessions/{session_id}/end")
    monkeypatch.undo()

    assert response.status_code == 409
    stored = store.get_session(session_id)
    assert stored is not None
    assert stored.status is SessionStatus.INTERVIEWING
    assert stored.started_at is not None
    assert media.closed == []


def test_end_before_start_is_allowed(client: TestClient, session_id: str):
    """면접 시작 전 취소. WAITING -> ENDED 로 바로 간다."""
    response = client.post(f"/api/v1/sessions/{session_id}/end")

    assert response.status_code == 200
    assert response.json()["status"] == "ENDED"


def test_end_unknown_session(client: TestClient):
    response = client.post("/api/v1/sessions/ses_nope/end")

    assert response.status_code == 404
