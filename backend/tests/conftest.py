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

    async def ensure_room(self, room: str) -> None:
        self.rooms.append(room)

    async def participant_count(self, room: str) -> int:
        return self.participants

    async def close_room(self, room: str) -> None:
        self.closed.append(room)

    def issue_token(self, room: str, role: Role) -> IssuedToken:
        return IssuedToken(
            token=f"fake.{room}.{role.value}",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )


@pytest.fixture
def media() -> FakeMedia:
    return FakeMedia()


@pytest.fixture
def client(media: FakeMedia) -> Iterator[TestClient]:
    store = InMemoryStore()
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
