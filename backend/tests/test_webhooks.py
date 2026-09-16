"""LiveKit Webhook — 전사 원점(t=0) 기록.

멘토 1차 리뷰 합의: t=0 = 첫 참가자 접속 시각.
`startedAt`(버튼)과 다른 값이라는 걸 여기서 고정한다.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Interview, Session
from app.domain.store import InMemoryStore

WEBHOOK = "/api/v1/livekit/webhook"
JOINED_AT = datetime(2026, 9, 16, 4, 30, 0, tzinfo=UTC)


class FakeEvent:
    """`WebhookEvent` 대역. 라우터가 쓰는 세 필드만 있으면 된다."""

    class _Room:
        def __init__(self, name: str) -> None:
            self.name = name

    def __init__(self, event: str, room: str, created_at: int) -> None:
        self.event = event
        self.room = self._Room(room)
        self.created_at = created_at


@pytest.fixture
def session(store: InMemoryStore) -> Session:
    interview = Interview(interviewer_id="user_123")
    store.add_interview(interview)
    created = Session(interview_id=interview.id)
    store.add_session(created)
    return created


def _post(client: TestClient, *, auth: str = "signed") -> int:
    headers = {"Authorization": auth} if auth else {}
    return client.post(WEBHOOK, content=b"{}", headers=headers).status_code


def test_participant_joined_sets_origin(client, media, store, session):
    media.webhook_event = FakeEvent(
        "participant_joined", session.room_name, int(JOINED_AT.timestamp())
    )

    assert _post(client) == 204
    assert store.get_session(session.id).transcript_origin_at == JOINED_AT


def test_origin_is_first_join_only(client, media, store, session):
    """두 번째 참가자와 재전송이 원점을 밀면 안 된다."""
    media.webhook_event = FakeEvent(
        "participant_joined", session.room_name, int(JOINED_AT.timestamp())
    )
    _post(client)

    later = int(JOINED_AT.timestamp()) + 600
    media.webhook_event = FakeEvent("participant_joined", session.room_name, later)
    assert _post(client) == 204

    assert store.get_session(session.id).transcript_origin_at == JOINED_AT


def test_origin_is_independent_of_started_at(client, media, store, session):
    """`startedAt` 은 버튼 시각이라 원점과 별개다 — 버튼을 안 눌러도 원점은 찍힌다."""
    media.webhook_event = FakeEvent(
        "participant_joined", session.room_name, int(JOINED_AT.timestamp())
    )
    _post(client)

    body = client.get(f"/api/v1/sessions/{session.id}").json()
    assert body["startedAt"] is None
    assert body["transcriptOriginAt"] is not None


@pytest.mark.parametrize(
    ("event", "room", "created_at"),
    [
        ("track_published", "{room}", 1789000000),  # 관심 없는 이벤트
        ("participant_joined", "lk-loadtest-3", 1789000000),  # 우리 방이 아님
        ("participant_joined", "interview_ses_nope", 1789000000),  # 없는 세션
        ("participant_joined", "{room}", 0),  # 시각이 비어 있음
    ],
)
def test_ignored_events_return_204(
    client, media, store, session, event, room, created_at
):
    """LiveKit 은 실패를 재시도한다. 처리 못 하는 건 조용히 204 로 삼킨다."""
    media.webhook_event = FakeEvent(
        event, room.format(room=session.room_name), created_at
    )

    assert _post(client) == 204
    assert store.get_session(session.id).transcript_origin_at is None


def test_unsigned_request_is_ignored(client, media, store, session):
    """서명이 없으면 무시하되, 응답은 똑같이 204 다 — 성공 여부를 알려주지 않는다."""
    media.webhook_event = FakeEvent(
        "participant_joined", session.room_name, int(JOINED_AT.timestamp())
    )

    assert _post(client, auth="") == 204
    assert store.get_session(session.id).transcript_origin_at is None


def test_webhook_is_not_in_public_spec(client):
    """클라이언트용 API 가 아니다. 명세에 실리면 FE 가 부를 것처럼 읽힌다."""
    paths = client.get("/openapi.json").json()["paths"]
    assert WEBHOOK not in paths
