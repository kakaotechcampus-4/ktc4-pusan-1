"""우리가 발급하는 access 토큰 (#118).

카카오 로그인이 끝나면 이 토큰 하나를 준다. FE 는 이걸 저장했다가 모든 요청의
`Authorization: Bearer` 에 싣는다 (`frontend/src/api/client.ts`).

refresh 토큰은 없다. 만료되면 401 이 나가고 FE 가 다시 카카오로 보낸다. 서버에
세션을 두지 않으므로 로그아웃은 FE 가 토큰을 지우는 것으로 끝난다.
"""

import logging
import secrets
from datetime import timedelta

import jwt

from app.core.config import settings
from app.domain.models import utcnow

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"

# 비어 있으면 기동할 때마다 새로 만든다. 로컬에서 설정 없이 로그인을 돌려 볼 수
# 있게 하려는 것이고, 재시작하면 전에 받은 토큰이 전부 401 이 된다. 운영은
# `check_secret_at_startup` 이 기동을 막는다.
_secret = settings.jwt_secret or secrets.token_hex(32)


def issue_token(user_id: str, version: int) -> str:
    """`version` 은 발급 시점의 `User.token_version` 이다.

    저장된 값이 올라가면 그 전에 발급한 토큰은 401 이 된다.
    """
    now = utcnow()
    claims = {
        "sub": user_id,
        "ver": version,
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_ttl_days),
    }
    return jwt.encode(claims, _secret, algorithm=_ALGORITHM)


def verified_claims(token: str) -> tuple[str, int] | None:
    """서명과 만료를 확인하고 (사용자 id, 토큰 버전) 을 꺼낸다. 하나라도 틀리면 None.

    `ver` 가 없는 토큰(#144 이전 발급)도 None 이다 — 다시 로그인하면 된다.
    """
    try:
        # algorithms 를 못박는다. 비우면 헤더의 alg 를 믿게 되어 `none` 토큰이 통과한다.
        claims = jwt.decode(
            token,
            _secret,
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "sub", "ver"]},
        )
    except jwt.InvalidTokenError:
        return None
    if not isinstance(claims["ver"], int):
        return None
    return claims["sub"], claims["ver"]


def check_secret_at_startup() -> None:
    """`check_key_at_startup` 과 같은 규칙이다. 로컬은 경고, 운영은 기동 거부.

    운영에서 비어 있으면 컨테이너가 재시작될 때마다 키가 바뀌어 모두가 로그아웃된다.
    """
    if settings.jwt_secret:
        return
    if settings.app_env == "production":
        raise RuntimeError(
            "JWT_SECRET 이 비어 있습니다. 운영에서는 재시작마다 로그인이 풀리므로 "
            "기동하지 않습니다. infra/.env 에 값을 넣으세요."
        )
    logger.warning(
        "JWT_SECRET 이 비어 있어 임시 키로 서명합니다. 재시작하면 토큰이 무효가 됩니다."
    )
