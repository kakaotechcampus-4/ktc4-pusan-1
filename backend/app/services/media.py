"""LiveKit 연동.

백엔드는 미디어 경로에 들어가지 않는다. 방을 미리 만들고 입장 토큰(JWT)을
서명해 줄 뿐이고, 실제 입장은 클라이언트가 wsUrl + token 으로 LiveKit 에
직접 붙으면서 이뤄진다.

라우터는 MediaGateway 프로토콜에만 의존한다 — 테스트에서 LiveKit 없이 돌리기 위해서다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from livekit import api

from app.core.config import settings
from app.domain.models import Role


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime


class MediaGateway(Protocol):
    async def ensure_room(self, room: str) -> None: ...

    async def participant_count(self, room: str) -> int: ...

    async def close_room(self, room: str) -> None: ...

    def issue_token(self, room: str, role: Role) -> IssuedToken: ...


def _grants_for(room: str, role: Role) -> api.VideoGrants:
    """입장 토큰 권한.

    명세는 역할별 권한 차이를 요구하지 않는다. 그래서 양쪽 모두 최소 권한만 준다 —
    지정된 방에 들어가서 주고받는 것까지다.

    roomAdmin(방 종료·강퇴) · roomRecord(녹화) · canPublishData 는 주지 않는다.
    canPublishData 는 SDK 기본값이 True 라 명시적으로 꺼야 한다.
    방 종료는 `POST /sessions/{id}/end` 로 BE 가 RoomService 를 부르고 Egress 제어도
    BE 몫이라, 클라이언트 토큰에 실을 이유가 없다. 토큰이 새도 방을 부술 수 없다.

    role 은 권한이 아니라 FE 화면 분기용으로만 쓰인다.
    """
    del role  # 현재 권한은 역할과 무관하다. 달라지면 여기서 갈린다.
    return api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
        # ⚠️ SDK 기본값이 True 다. 안 끄면 최소 권한이 되지 않는다.
        can_publish_data=False,
    )


class LiveKitGateway:
    def __init__(self, url: str, key: str, secret: str, max_participants: int) -> None:
        self._url = url
        self._key = key
        self._secret = secret
        self._max_participants = max_participants

    def _client(self) -> api.LiveKitAPI:
        # RoomService 는 HTTP 로 부른다. ws:// 를 http:// 로 바꿔 준다.
        http_url = self._url.replace("wss://", "https://").replace("ws://", "http://")
        return api.LiveKitAPI(http_url, self._key, self._secret)

    async def ensure_room(self, room: str) -> None:
        """방을 미리 만든다.

        LiveKit 은 입장 시 방을 자동 생성하지만, max_participants 같은 설정을
        적용하려면 사전 생성이 필요하다.
        """
        client = self._client()
        try:
            await client.room.create_room(
                api.CreateRoomRequest(
                    name=room, max_participants=self._max_participants
                )
            )
        finally:
            await client.aclose()

    async def participant_count(self, room: str) -> int:
        """사람 수.

        Agent·Egress 는 LiveKit 이 정원 계산에서 제외하므로 여기에도 안 잡힌다.
        """
        client = self._client()
        try:
            result = await client.room.list_participants(
                api.ListParticipantsRequest(room=room)
            )
            return len(result.participants)
        finally:
            await client.aclose()

    async def close_room(self, room: str) -> None:
        client = self._client()
        try:
            await client.room.delete_room(api.DeleteRoomRequest(room=room))
        finally:
            await client.aclose()

    def issue_token(self, room: str, role: Role) -> IssuedToken:
        """입장 토큰을 서명한다.

        identity 를 역할 문자열로 고정한다. 같은 역할로 다시 들어오면 LiveKit 이
        기존 세션을 DUPLICATE_IDENTITY 로 끊으므로, 재입장이 되면서도
        사람 수가 역할 수(2)를 넘지 않는다.
        """
        ttl = timedelta(minutes=settings.token_ttl_minutes)
        token = (
            api.AccessToken(self._key, self._secret)
            .with_identity(role.value)
            .with_name(role.value)
            .with_grants(_grants_for(room, role))
            .with_ttl(ttl)
        )
        return IssuedToken(token=token.to_jwt(), expires_at=datetime.now(UTC) + ttl)


media: MediaGateway = LiveKitGateway(
    url=settings.livekit_url,
    key=settings.livekit_api_key,
    secret=settings.livekit_api_secret,
    max_participants=settings.room_max_participants,
)
