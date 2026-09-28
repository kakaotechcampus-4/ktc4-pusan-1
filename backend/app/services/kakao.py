"""카카오 로그인 연동 (#118).

FE 가 카카오 인가 화면에서 받아 온 `code` 를 카카오 토큰으로 바꾸고, 그 토큰으로
사용자 정보를 한 번 읽는다. 카카오 토큰은 여기서 쓰고 버린다 — 저장하지 않는다.

    POST https://kauth.kakao.com/oauth/token   (code → 카카오 access_token)
    GET  https://kapi.kakao.com/v2/user/me     (access_token → 회원번호·닉네임)

HTTP 는 stdlib 로 부른다. 두 번 부르는 게 전부라 클라이언트 라이브러리를 들일
이유가 없고, 라우터가 `def` 라 스레드풀에서 돌아 이벤트 루프를 막지 않는다.

라우터는 KakaoGateway 프로토콜에만 의존한다 — 테스트에서 카카오 없이 돌리기 위해서다.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import status

from app.core.config import settings
from app.core.errors import ApiError, ErrorCode

logger = logging.getLogger(__name__)

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
USER_URL = "https://kapi.kakao.com/v2/user/me"
_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class KakaoProfile:
    kakao_id: int
    nickname: str
    profile_image_url: str | None


class KakaoGateway(Protocol):
    def login(self, code: str) -> KakaoProfile:
        """인가 코드로 카카오 사용자를 확인한다.

        카카오가 코드를 거절하면 401 `KAKAO_AUTH_FAILED`, 카카오에 닿지 못하면
        502 `KAKAO_UNAVAILABLE` 을 던진다.
        """
        ...


def _auth_failed() -> ApiError:
    return ApiError(
        ErrorCode.KAKAO_AUTH_FAILED,
        status.HTTP_401_UNAUTHORIZED,
        "카카오 인증에 실패했습니다.",
    )


def _unavailable() -> ApiError:
    return ApiError(
        ErrorCode.KAKAO_UNAVAILABLE,
        status.HTTP_502_BAD_GATEWAY,
        "카카오 서버에 연결할 수 없습니다.",
        retryable=True,
    )


def _call(request: Request) -> dict[str, Any]:
    """카카오를 부르고 JSON 을 돌려준다. 실패를 우리 에러 둘로 나눈다.

    4xx 는 우리가 보낸 값이 틀린 것이다 (만료·재사용된 code, 잘못된 키). 다시
    보내도 같으니 재시도하지 않는 쪽으로 보낸다. 5xx 와 네트워크 실패는 카카오
    사정이라 재시도할 수 있다.
    """
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        # 본문의 `error_code`(KOE320 등)만 남긴다. 토큰·code 가 섞일 수 있어 통째로
        # 로그에 쓰지 않는다.
        try:
            detail = json.loads(exc.read()).get("error_code", "")
        except ValueError:
            detail = ""
        logger.warning("카카오 %s 응답 %s %s", request.full_url, exc.code, detail)
        if exc.code < 500:
            raise _auth_failed() from exc
        raise _unavailable() from exc
    except (URLError, TimeoutError) as exc:
        logger.warning("카카오 %s 연결 실패: %s", request.full_url, exc)
        raise _unavailable() from exc


class KakaoClient:
    def login(self, code: str) -> KakaoProfile:
        form = {
            "grant_type": "authorization_code",
            "client_id": settings.kakao_client_id,
            "redirect_uri": settings.kakao_redirect_uri,
            "code": code,
        }
        # 콘솔에서 Client Secret 을 켜지 않았으면 보내지 않는다. 켰는데 안 보내면
        # 카카오가 거절한다.
        if settings.kakao_client_secret:
            form["client_secret"] = settings.kakao_client_secret
        token = _call(
            Request(
                TOKEN_URL,
                data=urlencode(form).encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
                },
            )
        )
        me = _call(
            Request(
                USER_URL,
                headers={"Authorization": f"Bearer {token['access_token']}"},
            )
        )
        # 닉네임·프로필 사진은 동의 항목이라 사용자가 거부하면 안 온다.
        profile = me.get("kakao_account", {}).get("profile", {})
        return KakaoProfile(
            kakao_id=me["id"],
            nickname=profile.get("nickname", ""),
            profile_image_url=profile.get("profile_image_url"),
        )


kakao: KakaoGateway = KakaoClient()
