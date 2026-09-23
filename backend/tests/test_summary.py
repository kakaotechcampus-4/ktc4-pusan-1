"""면접 요약 조회 — FE 가 목으로 돌리던 `GET /sessions/{id}/summary`.

지금 나가는 건 `PROCESSING` 한 갈래뿐이다. 요약을 만드는 쪽이 BE 에 안 붙었다(#70).
그래도 `durationSec` 은 진짜 값이라 그쪽을 본다.
"""

from fastapi.testclient import TestClient

V1 = "/api/v1"


def test_summary_is_processing_with_the_fe_shape(
    client: TestClient, session_id: str
) -> None:
    got = client.get(f"{V1}/sessions/{session_id}/summary")
    assert got.status_code == 202
    body = got.json()
    # FE 의 InterviewSummary 그대로.
    assert set(body) == {"sessionId", "status", "content", "durationSec"}
    assert body["sessionId"] == session_id
    assert body["status"] == "PROCESSING"
    # content 는 READY 일 때만 찬다.
    assert body["content"] is None


def test_duration_is_zero_before_the_interview_starts(
    client: TestClient, session_id: str
) -> None:
    assert client.get(f"{V1}/sessions/{session_id}/summary").json()["durationSec"] == 0


def test_duration_is_zero_while_the_interview_runs(
    client: TestClient, session_id: str
) -> None:
    """아직 안 끝났으면 잴 수가 없다. 지어내지 않는다."""
    client.post(f"{V1}/sessions/{session_id}/start")
    assert client.get(f"{V1}/sessions/{session_id}/summary").json()["durationSec"] == 0


def test_duration_is_counted_between_start_and_end(
    client: TestClient, session_id: str
) -> None:
    from datetime import timedelta

    from app.api.deps import get_store

    client.post(f"{V1}/sessions/{session_id}/start")

    # 실제로 기다리지 않고 시작 시각을 뒤로 민다.
    store = client.app.dependency_overrides[get_store]()  # pyright: ignore[reportFunctionMemberAccess]
    session = store.get_session(session_id)
    assert session is not None and session.started_at is not None
    session.started_at -= timedelta(seconds=125)
    store.save_session(session)

    client.post(f"{V1}/sessions/{session_id}/end")
    assert (
        client.get(f"{V1}/sessions/{session_id}/summary").json()["durationSec"] == 125
    )


def test_summary_of_an_unknown_session_is_404(client: TestClient) -> None:
    assert client.get(f"{V1}/sessions/ses_없는것/summary").status_code == 404
