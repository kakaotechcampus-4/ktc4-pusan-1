"""꼬리질문을 면접관에게 보내고 다시 읽는다 (#212).

Agent 가 내부 API 로 보낸 꼬리질문이 **면접관에게만 한 번** 가는지, 보내지 못해도
저장은 되는지, 그리고 조회 API 가 같은 모양으로 돌려주는지를 본다.
"""

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.internal.suggestions import SUGGESTION_TOPIC
from app.domain.models import Suggestion
from app.domain.store import InMemoryStore
from tests.conftest import FakeMedia

SUGGESTION = {
    "suggestionId": "sug_001",
    "content": "그 경험에서 가장 어려웠던 부분은 무엇이었나요?",
    "evidenceUtteranceIds": ["utt_002", "utt_001"],
}


def post(client: TestClient, session_id: str, body: dict = SUGGESTION):
    return client.post(f"/internal/v1/sessions/{session_id}/suggestions", json=body)


# ── 실시간 전달 ─────────────────────────────────────────


def test_new_suggestion_goes_to_the_interviewer_only(
    client: TestClient, session_id: str, media: FakeMedia, store: InMemoryStore
) -> None:
    assert post(client, session_id).status_code == 204

    [(room, data, topic, to)] = media.sent
    session = store.get_session(session_id)
    assert session is not None
    assert room == session.room_name
    assert topic == SUGGESTION_TOPIC
    assert to == ["INTERVIEWER"]
    packet = json.loads(data)
    assert packet["suggestionId"] == "sug_001"
    assert packet["content"] == SUGGESTION["content"]
    assert packet["evidenceUtteranceIds"] == ["utt_002", "utt_001"]
    assert packet["status"] == "NEW"
    assert "createdAt" in packet


def test_retried_suggestion_is_not_sent_again(
    client: TestClient, session_id: str, media: FakeMedia
) -> None:
    post(client, session_id)
    assert post(client, session_id).status_code == 204

    assert len(media.sent) == 1


def test_send_failure_still_stores_the_suggestion(
    client: TestClient, session_id: str, media: FakeMedia, store: InMemoryStore
) -> None:
    """저장이 성공하면 204 를 준다. 실시간 전달 실패는 FE 가 조회 API 로 복구한다."""
    media.send_error = RuntimeError("livekit down")

    assert post(client, session_id).status_code == 204
    assert [s.suggestion_id for s in store.list_suggestions(session_id)] == ["sug_001"]


def test_unknown_session_sends_nothing(client: TestClient, media: FakeMedia) -> None:
    assert post(client, "ses_x").status_code == 404
    assert media.sent == []


def test_ended_session_stores_without_sending(
    client: TestClient, session_id: str, media: FakeMedia, store: InMemoryStore
) -> None:
    assert client.post(f"/api/v1/sessions/{session_id}/end").status_code == 200

    assert post(client, session_id).status_code == 204

    assert media.sent == []
    assert [s.suggestion_id for s in store.list_suggestions(session_id)] == ["sug_001"]


# ── 조회 ────────────────────────────────────────────────


def test_list_is_empty_before_any_suggestion(
    client: TestClient, session_id: str
) -> None:
    got = client.get(f"/api/v1/sessions/{session_id}/suggestions")

    assert got.status_code == 200
    assert got.json() == {"items": []}


def test_list_returns_suggestions_in_arrival_order(
    client: TestClient, session_id: str, store: InMemoryStore
) -> None:
    for suggestion_id, hour in [("sug_b", 3), ("sug_a", 1)]:
        store.add_suggestion(
            Suggestion(
                session_id=session_id,
                suggestion_id=suggestion_id,
                content="질문",
                evidence_utterance_ids=["utt_001"],
                created_at=datetime(2026, 10, 17, hour, tzinfo=UTC),
            )
        )

    items = client.get(f"/api/v1/sessions/{session_id}/suggestions").json()["items"]

    assert [i["suggestionId"] for i in items] == ["sug_a", "sug_b"]


def test_list_item_matches_the_live_packet(
    client: TestClient, session_id: str, media: FakeMedia
) -> None:
    """FE 가 실시간 수신분과 조회분을 같은 타입으로 합친다."""
    post(client, session_id)

    [item] = client.get(f"/api/v1/sessions/{session_id}/suggestions").json()["items"]

    assert item == json.loads(media.sent[0][1])
