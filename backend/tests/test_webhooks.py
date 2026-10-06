"""LiveKit Webhook — 전사 원점(t=0) 기록.

멘토 1차 리뷰 합의: t=0 = 첫 참가자 접속 시각.
`startedAt`(버튼)과 다른 값이라는 걸 여기서 고정한다.
"""

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from livekit.protocol.models import ParticipantInfo

from app.domain.models import Interview, Session
from app.domain.store import InMemoryStore

WEBHOOK = "/api/v1/livekit/webhook"
#: ms 까지 있는 시각이다. 원점이 초 단위로 잘리면 기대값과 달라 잡힌다.
JOINED_AT = datetime(2026, 9, 16, 4, 30, 0, 123000, tzinfo=UTC)
JOINED_MS = int(JOINED_AT.timestamp()) * 1000 + 123

STANDARD = ParticipantInfo.Kind.STANDARD
AGENT = ParticipantInfo.Kind.AGENT
EGRESS = ParticipantInfo.Kind.EGRESS


class FakeEvent:
    """`WebhookEvent` 대역. 라우터가 읽는 필드만 있다."""

    class _Room:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Participant:
        def __init__(self, joined_at_ms: int, kind: int) -> None:
            self.joined_at_ms = joined_at_ms
            self.kind = kind

    def __init__(
        self, event: str, room: str, joined_at_ms: int, kind: int = STANDARD
    ) -> None:
        self.event = event
        self.room = self._Room(room)
        self.participant = self._Participant(joined_at_ms, kind)


@pytest.fixture
def session(store: InMemoryStore) -> Session:
    interview = Interview(interviewer_id="user_123")
    store.add_interview(interview)
    created = Session(interview_id=interview.id)
    store.add_session(created)
    return created


def _post(client: TestClient, *, auth: str = "signed") -> int:
    # 빈 값도 실어야 한다 — 안 실으면 `client` 의 기본 로그인 헤더가 대신 간다.
    return client.post(
        WEBHOOK, content=b"{}", headers={"Authorization": auth}
    ).status_code


def test_participant_joined_sets_origin(client, media, store, session):
    media.webhook_event = FakeEvent("participant_joined", session.room_name, JOINED_MS)

    assert _post(client) == 204
    assert store.get_session(session.id).transcript_origin_at == JOINED_AT


def test_origin_is_first_join_only(client, media, store, session):
    """늦게 들어온 참가자와 재전송이 원점을 밀면 안 된다."""
    media.webhook_event = FakeEvent("participant_joined", session.room_name, JOINED_MS)
    _post(client)

    later = JOINED_MS + 600
    media.webhook_event = FakeEvent("participant_joined", session.room_name, later)
    assert _post(client) == 204

    assert store.get_session(session.id).transcript_origin_at == JOINED_AT


def test_origin_is_written_off_the_event_loop(
    client, media, store, session, monkeypatch
):
    """동기 저장소를 이벤트 루프에서 부르면 그동안 다른 요청이 줄을 선다 (#133).

    스레드풀로 넘겼으면 그 스레드에는 돌고 있는 이벤트 루프가 없다.
    """
    mark = store.mark_origin
    on_loop: list[bool] = []

    def spy(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return mark(*args, **kwargs)

    monkeypatch.setattr(store, "mark_origin", spy)
    media.webhook_event = FakeEvent("participant_joined", session.room_name, JOINED_MS)

    assert _post(client) == 204
    assert on_loop == [False]


def test_origin_is_independent_of_started_at(client, media, store, session):
    """`startedAt` 은 버튼 시각이라 원점과 별개다 — 버튼을 안 눌러도 원점은 찍힌다."""
    media.webhook_event = FakeEvent("participant_joined", session.room_name, JOINED_MS)
    _post(client)

    body = client.get(f"/api/v1/sessions/{session.id}").json()
    assert body["startedAt"] is None
    assert body["transcriptOriginAt"] is not None


@pytest.mark.parametrize("kind", [AGENT, EGRESS])
def test_non_human_participant_is_not_origin(client, media, store, session, kind):
    """자막 워커(AGENT) · 녹화(EGRESS)가 사람보다 먼저 들어와도 원점이 아니다 (#86)."""
    media.webhook_event = FakeEvent(
        "participant_joined", session.room_name, JOINED_MS - 5000, kind
    )
    _post(client)
    assert store.get_session(session.id).transcript_origin_at is None

    media.webhook_event = FakeEvent("participant_joined", session.room_name, JOINED_MS)
    _post(client)
    assert store.get_session(session.id).transcript_origin_at == JOINED_AT


def test_late_event_arriving_first_does_not_win(client, media, store, session):
    """참가자마다 webhook 이 따로 와 순서가 뒤바뀔 수 있다. 가장 이른 입장이 원점."""
    media.webhook_event = FakeEvent(
        "participant_joined", session.room_name, JOINED_MS + 3000
    )
    _post(client)
    media.webhook_event = FakeEvent("participant_joined", session.room_name, JOINED_MS)
    _post(client)

    assert store.get_session(session.id).transcript_origin_at == JOINED_AT


@pytest.mark.parametrize(
    ("event", "room", "joined_at_ms"),
    [
        ("track_published", "{room}", 1789000000),  # 관심 없는 이벤트
        ("participant_joined", "lk-loadtest-3", 1789000000),  # 우리 방이 아님
        ("participant_joined", "interview_ses_nope", 1789000000),  # 없는 세션
        ("participant_joined", "{room}", 0),  # 시각이 비어 있음
    ],
)
def test_ignored_events_return_204(
    client, media, store, session, event, room, joined_at_ms
):
    """LiveKit 은 실패를 재시도한다. 처리 못 하는 건 조용히 204 로 삼킨다."""
    media.webhook_event = FakeEvent(
        event, room.format(room=session.room_name), joined_at_ms
    )

    assert _post(client) == 204
    assert store.get_session(session.id).transcript_origin_at is None


def test_unsigned_request_is_ignored(client, media, store, session):
    """서명이 없으면 무시하되, 응답은 똑같이 204 다 — 성공 여부를 알려주지 않는다."""
    media.webhook_event = FakeEvent("participant_joined", session.room_name, JOINED_MS)

    assert _post(client, auth="") == 204
    assert store.get_session(session.id).transcript_origin_at is None


def test_webhook_is_not_in_public_spec(client):
    """클라이언트용 API 가 아니다. 명세에 실리면 FE 가 부를 것처럼 읽힌다."""
    paths = client.get("/openapi.json").json()["paths"]
    assert WEBHOOK not in paths


def test_signature_failure_is_logged(client, media, store, session, caplog):
    """응답은 204 로 감추되 로그에는 남겨야 한다.

    BE 의 키 쌍이 LiveKit 의 `LIVEKIT_KEYS` 와 어긋나면 모든 이벤트가 버려지는데,
    LiveKit 도 204 를 받아 재시도하지 않는다. 로그가 유일한 단서다.
    """
    media.webhook_event = FakeEvent("participant_joined", session.room_name, JOINED_MS)

    with caplog.at_level(logging.WARNING, logger="app.api.v1.webhooks"):
        assert _post(client, auth="") == 204

    assert "서명 검증 실패" in caplog.text
    assert "LIVEKIT_KEYS" in caplog.text


def test_ignored_event_is_not_a_warning(client, media, store, session, caplog):
    """관심 없는 이벤트는 정상이다. warning 으로 남기면 로그가 쓸모없어진다."""
    media.webhook_event = FakeEvent("track_published", session.room_name, JOINED_MS)

    with caplog.at_level(logging.WARNING, logger="app.api.v1.webhooks"):
        assert _post(client) == 204

    assert caplog.text == ""


def test_success_is_logged(client, media, store, session, caplog):
    media.webhook_event = FakeEvent("participant_joined", session.room_name, JOINED_MS)

    with caplog.at_level(logging.INFO, logger="app.api.v1.webhooks"):
        assert _post(client) == 204

    assert "전사 원점 기록" in caplog.text
