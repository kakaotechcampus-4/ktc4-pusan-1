"""라우터 의존성.

라우터는 구현체가 아니라 Protocol 에만 의존한다. 테스트에서
`app.dependency_overrides` 로 갈아끼우고, DB 가 정해지면 여기만 바꾼다.
"""

from typing import Annotated

from fastapi import Depends, Header, status

from app.core.auth import verified_user_id
from app.core.errors import ApiError, ErrorCode
from app.domain import store as store_module
from app.domain.models import User
from app.domain.store import Store
from app.services import kakao as kakao_module
from app.services import media as media_module
from app.services.kakao import KakaoGateway
from app.services.media import MediaGateway


def get_store() -> Store:
    return store_module.store


def get_media() -> MediaGateway:
    return media_module.media


def get_kakao() -> KakaoGateway:
    return kakao_module.kakao


StoreDep = Annotated[Store, Depends(get_store)]
MediaDep = Annotated[MediaGateway, Depends(get_media)]
KakaoDep = Annotated[KakaoGateway, Depends(get_kakao)]

_BEARER = "Bearer "


def get_current_user(store: StoreDep, authorization: str = Header(default="")) -> User:
    """`Authorization: Bearer <accessToken>` 의 주인. 아니면 401 `UNAUTHORIZED`.

    헤더 없음·서명 불일치·만료·탈퇴한 사용자를 구분하지 않는다. FE 는 어느 쪽이든
    다시 로그인시키면 되고, 구분해 주면 토큰을 떠보는 쪽에만 도움이 된다.
    """
    user_id = None
    if authorization.startswith(_BEARER):
        user_id = verified_user_id(authorization[len(_BEARER) :])
    user = None if user_id is None else store.get_user(user_id)
    if user is None:
        raise ApiError(
            ErrorCode.UNAUTHORIZED, status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다."
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
