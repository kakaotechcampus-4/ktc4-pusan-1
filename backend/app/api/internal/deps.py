"""`/internal/v1` 인증.

Agent 는 핸드셰이크에 `Authorization: Bearer <공유 비밀>` 을 실어 보낸다
(`irya_ai.backend.auth_headers`). 브라우저가 부르는 API 가 아니므로 토큰 발급
절차를 두지 않고, 배포 때 양쪽 컨테이너에 같은 값을 넣는 공유 비밀 하나로 둔다.

`settings.internal_api_key` 가 비어 있으면 **검사하지 않는다.** Agent 쪽도 키가
없으면 헤더를 아예 보내지 않으므로, 둘 다 비어 있는 로컬에서는 자격증명을 지어내지
않고 그대로 붙는다. 대신 그 사실을 기동 때 한 번 경고로 남긴다 — 서버에서 비어
있으면 `/internal/v1` 이 누구에게나 열린다.

⚠️ HTTP 와 WebSocket 이 실패를 알리는 방법이 다르다. HTTP 는 401 이고, WebSocket 은
101 로 올라가기 전에 거절해야 Agent 의 `status_error` 가 `BACKEND_AUTH_FAILED`
(재시도 안 함) 로 분류한다. 붙은 뒤에 close 하면 Agent 는 연결이 끊긴 것으로 보고
재시도한다 — 키가 틀린 채로 무한히.
"""

import logging
import secrets

from fastapi import Header, WebSocket, status

from app.core.config import settings
from app.core.errors import ApiError, ErrorCode

logger = logging.getLogger(__name__)

_BEARER = "Bearer "


def _presented(authorization: str) -> str | None:
    """`Authorization` 헤더에서 Bearer 토큰만 꺼낸다."""
    if not authorization.startswith(_BEARER):
        return None
    return authorization[len(_BEARER) :]


def _accepted(authorization: str) -> bool:
    """공유 비밀이 맞는지. 키가 설정돼 있지 않으면 항상 통과한다."""
    expected = settings.internal_api_key
    if not expected:
        return True
    token = _presented(authorization)
    if token is None:
        return False
    # 앞자리부터 비교해 길이로 정답을 좁힐 수 있는 걸 막는다.
    return secrets.compare_digest(token, expected)


def require_internal_auth(authorization: str = Header(default="")) -> None:
    """HTTP 라우트용 의존성.

    실패를 401 로 준다. Agent 의 `status_error` 가 401·403 을 재시도하지 않는
    `BACKEND_AUTH_FAILED` 로 분류하므로, 키가 틀린 요청이 되풀이되지 않는다.
    """
    if _accepted(authorization):
        return
    # 무엇이 왔는지는 남기지 않는다 — 우리가 발급한 값이 아니라 신뢰할 수 없고,
    # 로그에 남기면 비밀이 로그로 새는 경로가 된다.
    logger.warning("internal API 인증 실패")
    raise ApiError(
        ErrorCode.NOT_FOUND, status.HTTP_401_UNAUTHORIZED, "인증이 필요합니다."
    )


async def websocket_authorized(websocket: WebSocket) -> bool:
    """WebSocket 핸드셰이크용. 통과하지 못하면 여기서 거절까지 한다.

    `accept()` 전에 `close()` 하면 Starlette 이 101 대신 HTTP 403 을 돌려준다.
    Agent 는 그걸 `BACKEND_AUTH_FAILED` 로 읽고 재시도하지 않는다.
    """
    if _accepted(websocket.headers.get("authorization", "")):
        return True
    logger.warning("internal WebSocket 인증 실패")
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    return False


def warn_if_open() -> None:
    """키가 비어 있으면 기동 때 한 번 알린다."""
    if not settings.internal_api_key:
        logger.warning(
            "INTERNAL_API_KEY 가 비어 있어 /internal/v1 인증을 건너뜁니다. "
            "서버 배포에서는 반드시 채우세요."
        )
