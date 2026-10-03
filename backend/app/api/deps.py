"""라우터 의존성.

라우터는 구현체가 아니라 Protocol 에만 의존한다. 테스트에서
`app.dependency_overrides` 로 갈아끼우고, DB 가 정해지면 여기만 바꾼다.
"""

from typing import Annotated

from fastapi import Depends, Header, Path, status

from app.core.auth import verified_user_id
from app.core.errors import ApiError, ErrorCode
from app.domain import store as store_module
from app.domain.models import Interview, Session, User
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


def get_optional_user(
    store: StoreDep, authorization: str = Header(default="")
) -> User | None:
    """`Authorization: Bearer <accessToken>` 의 주인. 없거나 무효면 None.

    헤더 없음·빈 `Bearer `·서명 불일치·만료·탈퇴한 사용자를 구분하지 않는다. FE 는
    어느 쪽이든 다시 로그인시키면 되고, 구분해 주면 토큰을 떠보는 쪽에만 도움이 된다.
    지원자는 로그인하지 않으므로 입장(join)은 이것을 쓴다.
    """
    if not authorization.startswith(_BEARER):
        return None
    user_id = verified_user_id(authorization[len(_BEARER) :])
    return None if user_id is None else store.get_user(user_id)


OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]


def get_current_user(user: OptionalUserDep) -> User:
    """로그인 필수. 아니면 401 `UNAUTHORIZED` — FE 가 토큰을 지우고 로그인시킨다."""
    if user is None:
        raise ApiError(
            ErrorCode.UNAUTHORIZED, status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다."
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]

# 아래 의존성은 「로그인한 사람의 것」만 돌려준다 (#130). 남의 것도 없는 것과 같은 404 ·
# 같은 코드로 답한다 — 403 이나 다른 코드를 주면 그 id 가 있다는 사실이 드러난다.
#
# 동기 의존성이라 FastAPI 가 스레드풀에서 돌린다. async 라우트가 이걸 받으면 DB
# 읽기가 이벤트 루프 밖으로 나간다 (#133).


def get_owned_interview(
    interview_id: Annotated[str, Path(alias="interviewId")],
    user: CurrentUserDep,
    store: StoreDep,
) -> Interview:
    interview = store.get_interview(interview_id)
    if interview is None or interview.interviewer_id != user.id:
        raise ApiError(ErrorCode.INTERVIEW_NOT_FOUND, 404, "면접을 찾을 수 없습니다.")
    return interview


def get_owned_session(
    session_id: Annotated[str, Path(alias="sessionId")],
    user: CurrentUserDep,
    store: StoreDep,
) -> Session:
    session = store.get_session(session_id)
    interview = None if session is None else store.get_interview(session.interview_id)
    if session is None or interview is None or interview.interviewer_id != user.id:
        raise ApiError(ErrorCode.SESSION_NOT_FOUND, 404, "Session 을 찾을 수 없습니다.")
    return session


OwnedInterviewDep = Annotated[Interview, Depends(get_owned_interview)]
OwnedSessionDep = Annotated[Session, Depends(get_owned_session)]
