"""`/internal/v1` — Agent 가 부르는 라우터.

`/api/v1` 은 브라우저가 부르고 이쪽은 Agent 가 부른다. 경로를 나눠 두면 둘이
섞이지 않고, Caddy 가 `/rtc*` · `/api/*` · `/health` 만 프록시하므로 `/internal`
은 설정을 더 하지 않아도 밖으로 열리지 않는다.

공개 명세에 싣지 않는다. FE 가 부를 것처럼 읽히면 안 되고, 이 계약은 Agent 와
우리 사이에서만 바뀐다.
"""

from fastapi import APIRouter

from app.api.internal import suggestions, transcripts

router = APIRouter()
router.include_router(transcripts.router)
router.include_router(suggestions.router)
