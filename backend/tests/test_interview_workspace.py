from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.models import Interview, Session
from app.infra.postgres import PostgresStore
from tests.conftest import age


def test_saved_memo_and_existing_invitation_before_analysis(client: TestClient, other):
    interview_id = client.post("/api/v1/interviews", json={}).json()["interviewId"]
    session = client.post(f"/api/v1/interviews/{interview_id}/sessions").json()
    client.patch(
        f"/api/v1/interviews/{interview_id}",
        json={"memo": "면접 중 메모", "expectedMemo": ""},
    )
    detail = client.get(f"/api/v1/interviews/{interview_id}").json()
    for _ in range(2):
        detail = client.get(f"/api/v1/interviews/{interview_id}").json()
        assert detail["memo"] == "면접 중 메모"
        assert detail["latestSession"]["sessionId"] == session["sessionId"]
        assert detail["latestSession"]["inviteUrl"] == session["inviteUrl"]
    assert (
        client.get(f"/api/v1/interviews/{interview_id}", headers=other).status_code
        == 404
    )
    item = client.get("/api/v1/interviews").json()["items"][0]
    assert item["memo"] == detail["memo"]
    assert item["latestSession"] == detail["latestSession"]
    assert item["reviewSessionId"] is None
    assert item["reportStatus"] is None


def test_latest_invitation_and_review_session_are_separate(client: TestClient):
    interview_id = client.post("/api/v1/interviews", json={}).json()["interviewId"]
    path = f"/api/v1/interviews/{interview_id}/sessions"
    first = client.post(path).json()["sessionId"]
    client.post(f"/api/v1/sessions/{first}/end")
    latest = client.post(path).json()["sessionId"]
    row = client.get("/api/v1/interviews").json()["items"][0]
    assert row["latestSession"]["sessionId"] == latest
    assert row["reviewSessionId"] == first


@pytest.mark.parametrize("size", [1, 1000])
def test_projection_queries_do_not_grow_per_interview(monkeypatch, size):
    store = object.__new__(PostgresStore)
    interviews = [Interview(interviewer_id="owner", id=f"int_{i}") for i in range(size)]
    monkeypatch.setattr(
        store, "list_interviews", lambda _: [(i, None, None) for i in interviews]
    )
    calls = []
    monkeypatch.setattr(
        store, "_all", lambda query, params: calls.append((query, params)) or []
    )
    result = store.list_interview_workspaces("owner")
    assert len(result) == size
    assert len(calls) == 6


def test_latest_session_tie_break_matches_postgres(store):
    interview = Interview(interviewer_id="owner")
    store.add_interview(interview)
    stamp = datetime(2026, 10, 30, tzinfo=UTC)
    for session_id in ["ses_b", "ses_a"]:
        store.add_session(
            Session(interview_id=interview.id, id=session_id, created_at=stamp)
        )
    assert store.latest_session(interview.id).id == "ses_b"


def test_expired_findings_match_before_and_after_opening_review(client, store):
    interview_id = client.post("/api/v1/interviews", json={}).json()["interviewId"]
    session_id = client.post(f"/api/v1/interviews/{interview_id}/sessions").json()[
        "sessionId"
    ]
    client.post(f"/api/v1/sessions/{session_id}/end")
    age(store, session_id, settings.summary_timeout + timedelta(seconds=1))
    before = client.get("/api/v1/interviews").json()["items"][0]
    detail = client.get(f"/api/v1/interviews/{interview_id}/review").json()
    after = client.get("/api/v1/interviews").json()["items"][0]
    assert before["summaryStatus"] == after["summaryStatus"] == "FAILED"
    assert (
        before["findingsStatus"]
        == detail["findingsStatus"]
        == after["findingsStatus"]
        == "FAILED"
    )
