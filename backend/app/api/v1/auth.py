"""카카오 로그인 (#118).

    FE ─(authorize)→ 카카오 ─(redirect ?code)→ FE 콜백
    FE ─POST /auth/kakao {code}→ BE ─(token·user/me)→ 카카오
    BE ─{accessToken, user}→ FE

카카오 인가 URL 은 FE 가 만든다 (client_id 는 비밀이 아니다). `state` 로 CSRF 를
막는 것도 FE 몫이다 — 인가 요청을 보낸 쪽만 그 값을 안다.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, KakaoDep, StoreDep
from app.core.auth import issue_token
from app.core.errors import responses
from app.domain.models import User
from app.schemas import KakaoLoginRequest, LoginResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["인증"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id, nickname=user.nickname, profile_image_url=user.profile_image_url
    )


@router.post(
    "/kakao",
    summary="카카오 로그인",
    response_model=LoginResponse,
    responses=responses(
        (401, "카카오가 code 를 거절함 (만료·재사용)"),
        (502, "카카오 서버에 닿지 못함. 재시도 가능"),
    ),
)
def kakao_login(
    body: KakaoLoginRequest, kakao: KakaoDep, store: StoreDep
) -> LoginResponse:
    """처음이면 가입, 이미 있으면 닉네임·프로필을 갱신하고 로그인한다."""
    profile = kakao.login(body.code)
    user = store.upsert_user(
        User(
            kakao_id=profile.kakao_id,
            nickname=profile.nickname,
            profile_image_url=profile.profile_image_url,
        )
    )
    return LoginResponse(
        access_token=issue_token(user.id, user.token_version), user=_user_response(user)
    )


@router.get(
    "/me",
    summary="내 정보",
    response_model=UserResponse,
    responses=responses((401, "토큰이 없거나 만료·위조됨. 다시 로그인한다")),
)
def me(user: CurrentUserDep) -> UserResponse:
    return _user_response(user)
