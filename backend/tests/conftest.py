"""테스트 공용 픽스처.

라우터가 Protocol 에만 의존하므로 LiveKit 없이 전 구간을 돈다.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_media, get_store
from app.domain.models import Role
from app.domain.store import InMemoryStore
from app.main import app
from app.services.media import IssuedToken


class FakeMedia:
    """LiveKit 대역. 호출 내역을 남겨 라우터가 무엇을 시켰는지 검증한다."""

    def __init__(self) -> None:
        self.rooms: list[str] = []
        self.closed: list[str] = []
        self.participants = 0
        self.webhook_event: object | None = None

    async def ensure_room(self, room: str) -> None:
        self.rooms.append(room)

    async def participant_count(self, room: str) -> int:
        return self.participants

    async def close_room(self, room: str) -> None:
        self.closed.append(room)

    def verify_webhook(self, body: str, auth_header: str):
        """서명 검증 대역.

        `auth_header` 를 그대로 신뢰한다 — 실제 검증은 SDK 몫이고, 여기서
        보려는 건 라우터가 이벤트를 어떻게 처리하는지다. 빈 헤더는 실패로 둔다.
        """
        if not auth_header:
            return None
        return self.webhook_event

    def issue_token(self, room: str, role: Role) -> IssuedToken:
        return IssuedToken(
            token=f"fake.{room}.{role.value}",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )


@pytest.fixture
def media() -> FakeMedia:
    return FakeMedia()


@pytest.fixture
def store() -> InMemoryStore:
    """테스트가 저장된 상태를 직접 들여다볼 수 있게 밖으로 뺀다."""
    return InMemoryStore()


@pytest.fixture
def client(media: FakeMedia, store: InMemoryStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_media] = lambda: media
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def session_id(client: TestClient) -> str:
    """면접 → 세션까지 만들어 둔 상태의 sessionId."""
    interview = client.post("/api/v1/interviews", json={"interviewerId": "user_123"})
    interview_id = interview.json()["interviewId"]
    created = client.post(f"/api/v1/interviews/{interview_id}/sessions")
    return created.json()["sessionId"]
