"""테스트 공용 픽스처.

라우터가 Protocol 에만 의존하므로 LiveKit 없이 전 구간을 돈다.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_kakao, get_media, get_store
from app.core.auth import issue_token
from app.core.errors import ApiError
from app.domain.models import Role, User
from app.domain.store import InMemoryStore
from app.main import app
from app.services import documents as documents_module
from app.services.kakao import KakaoProfile
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


class FakeKakao:
    """카카오 대역. code 하나에 프로필 하나를 돌려준다.

    `error` 를 채우면 그걸 던진다 — 실제 클라이언트가 카카오 실패를 바꿔 던지는
    `ApiError` 와 같은 것을 넣는다.
    """

    def __init__(self) -> None:
        self.profile = KakaoProfile(
            kakao_id=4242, nickname="김면접", profile_image_url="https://k.kakao/p.jpg"
        )
        self.error: ApiError | None = None
        self.codes: list[str] = []

    def login(self, code: str) -> KakaoProfile:
        self.codes.append(code)
        if self.error is not None:
            raise self.error
        return self.profile


class FakeParser:
    """Helpy Document Vision 대역. 받은 파일을 남기고 정해 둔 본문을 돌려준다.

    ⚠️ 이게 없으면 테스트가 `.env` 의 키로 실제 Helpy 를 부른다 (페이지당 과금).
    """

    def __init__(self) -> None:
        self.text: str | None = "추출한 본문"
        self.calls: list[tuple[str, bytes]] = []

    def extract_text(self, name: str, content: bytes) -> str | None:
        self.calls.append((name, content))
        return self.text


@pytest.fixture(autouse=True)
def parser(monkeypatch: pytest.MonkeyPatch) -> FakeParser:
    """모든 테스트에서 실제 Helpy 를 막는다. `client` 를 안 쓰는 테스트도 포함한다."""
    fake = FakeParser()
    monkeypatch.setattr(documents_module, "parser", fake)
    return fake


@pytest.fixture
def kakao() -> FakeKakao:
    return FakeKakao()


@pytest.fixture
def media() -> FakeMedia:
    return FakeMedia()


@pytest.fixture
def store() -> InMemoryStore:
    """테스트가 저장된 상태를 직접 들여다볼 수 있게 밖으로 뺀다."""
    return InMemoryStore()


def bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(user.id, user.token_version)}"}


#: 요청에 실으면 기본 헤더의 주인 토큰을 덮어써 로그인하지 않은 요청이 된다.
ANON = {"Authorization": ""}


@pytest.fixture
def owner(store: InMemoryStore) -> User:
    """`client` 가 로그인해 있는 면접관. 이 사람이 만든 면접 · 컨텍스트가 그의 것."""
    return store.upsert_user(User(kakao_id=1, nickname="면접관"))


@pytest.fixture
def other(store: InMemoryStore) -> dict[str, str]:
    """다른 면접관의 인증 헤더. 남의 자원에 닿는지 볼 때 요청마다 싣는다."""
    return bearer(store.upsert_user(User(kakao_id=2, nickname="다른 면접관")))


@pytest.fixture
def client(
    media: FakeMedia, store: InMemoryStore, kakao: FakeKakao, owner: User
) -> Iterator[TestClient]:
    """`owner` 로 로그인한 클라이언트 (#130). 면접관 API 가 전부 로그인을 요구한다."""
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_media] = lambda: media
    app.dependency_overrides[get_kakao] = lambda: kakao
    with TestClient(app, headers=bearer(owner)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def session_id(client: TestClient) -> str:
    """면접 → 세션까지 만들어 둔 상태의 sessionId."""
    interview = client.post("/api/v1/interviews", json={"interviewerId": "user_123"})
    interview_id = interview.json()["interviewId"]
    created = client.post(f"/api/v1/interviews/{interview_id}/sessions")
    return created.json()["sessionId"]
