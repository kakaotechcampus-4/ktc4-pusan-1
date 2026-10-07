"""면접 · 세션 생성 — 명세 `면접` 카테고리."""

from datetime import timedelta

from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.models import (
    FindingState,
    ReviewStatus,
    SummaryStatus,
    User,
)
from app.domain.store import InMemoryStore
from tests.conftest import FakeMedia
from tests.test_reviews import DEMO, _analysed, _prepared


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


# ── 내 면접 목록 (#137 1-1) ─────────────────────────────


def test_list_is_mine_newest_first_on_last_ended_session(
    client: TestClient, other: dict[str, str]
):
    context_id = client.get("/api/v1/contexts/current").json()["id"]
    client.patch(f"/api/v1/contexts/{context_id}", json={"role": "백엔드 개발자"})
    first = client.post("/api/v1/interviews", json={"candidateName": "가"}).json()
    second = client.post("/api/v1/interviews", json={"candidateName": "나"}).json()
    client.post("/api/v1/interviews", json={}, headers=other)
    path = f"/api/v1/interviews/{first['interviewId']}/sessions"
    ended = client.post(path).json()["sessionId"]
    client.post(f"/api/v1/sessions/{ended}/start")
    client.post(f"/api/v1/sessions/{ended}/end")
    client.post(path)  # 나중에 만들었지만 안 끝난 세션은 기준이 아니다

    response = client.get("/api/v1/interviews")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["interviewId"] for i in items] == [
        second["interviewId"],
        first["interviewId"],
    ]
    assert items[0] == {
        "interviewId": second["interviewId"],
        "candidateName": "나",
        "role": "백엔드 개발자",
        "interviewer": {"nickname": "면접관"},
        "interviewedAt": None,
        "durationSec": None,
        "reviewStatus": "PENDING",
        "summaryStatus": None,
        "counts": None,
    }
    done = items[1]
    assert done["interviewedAt"] is not None
    assert done["durationSec"] == 0
    assert done["summaryStatus"] == "PROCESSING"
    assert done["counts"] is None


def test_list_is_empty_for_a_new_interviewer(client: TestClient):
    assert client.get("/api/v1/interviews").json() == {"items": []}


# ── 검토 상태와 집계 (#163) ──────────────────────────────


def _ended(client: TestClient, interview_id: str) -> str:
    session_id = client.post(f"/api/v1/interviews/{interview_id}/sessions").json()[
        "sessionId"
    ]
    client.post(f"/api/v1/sessions/{session_id}/start")
    client.post(f"/api/v1/sessions/{session_id}/end")
    return session_id


def test_a_ready_row_counts_like_the_detail(client: TestClient, store: InMemoryStore):
    """목록과 상세가 같은 계산을 쓴다 — 숫자가 어긋나지 않는다 (#137 1-1)."""
    interview_id = client.post("/api/v1/interviews", json={}).json()["interviewId"]
    session_id = _ended(client, interview_id)
    _prepared(store, interview_id)
    _analysed(store, session_id)
    store.update_mark(
        session_id,
        DEMO["review"]["findings"][0]["findingId"],
        state=FindingState.ADOPTED,
    )
    store.update_review(interview_id, ReviewStatus.IN_REVIEW, None)

    [item] = client.get("/api/v1/interviews").json()["items"]

    assert (item["summaryStatus"], item["reviewStatus"]) == ("READY", "IN_REVIEW")
    assert item["counts"] == {
        "coverageConfirmed": 1,
        "coverageTotal": 4,
        "findings": 5,
        "needsReview": 4,
        "adopted": 1,
    }


def test_a_summary_past_its_limit_shows_failed_without_counts(
    client: TestClient, store: InMemoryStore
):
    """아무도 요약 화면을 열지 않아도 목록에서 영원히 「처리 중」이지 않다. 보여 줄
    뿐 쓰지 않는다 — 판정과 저장은 요약 · 상세 조회가 한다."""
    interview_id = client.post("/api/v1/interviews", json={}).json()["interviewId"]
    session_id = _ended(client, interview_id)
    stored = store._summaries[session_id]  # pyright: ignore[reportPrivateUsage]
    stored.requested_at -= settings.summary_timeout + timedelta(seconds=1)

    [item] = client.get("/api/v1/interviews").json()["items"]

    assert (item["summaryStatus"], item["counts"]) == ("FAILED", None)
    stored_after = store.get_summary(session_id)
    assert stored_after is not None
    assert stored_after.status is SummaryStatus.PROCESSING
