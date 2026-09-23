"""본문이 너무 큰 요청을 라우터에 닿기 전에 끊는다.

라우터 안에서 `Content-Length` 를 보는 것으로는 늦다. `file: UploadFile = File()`
같은 파라미터가 있으면 **FastAPI 가 핸들러에 들어가기 전에 multipart 를 전부
파싱한다.** 그래서 핸들러 첫 줄에서 헤더를 봐도 그때는 이미 본문을 다 받은 뒤다.
1GB 를 선언하고 1KB 만 보내면 서버가 나머지를 계속 기다리는 것으로 확인했다.

미들웨어는 그보다 앞이라 헤더만 보고 끊을 수 있다.

Caddy 에 `request_body { max_size }` 를 거는 방법도 있고 그쪽이 더 앞이지만,
`/internal/v1` 처럼 Caddy 를 거치지 않는 경로가 이미 있어서 앱에도 있어야 한다.
둘 다 두는 것이 맞다.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import ErrorCode, error_body

logger = logging.getLogger(__name__)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """`Content-Length` 가 상한을 넘으면 본문을 읽기 전에 413 을 준다.

    헤더가 없으면(청크 전송) 통과시킨다 — 그때는 라우터의 읽은 뒤 검사가 받는다.
    거짓말한 길이도 통과하지만, 그것도 읽은 뒤 검사에 걸린다. 여기서 막으려는 건
    「정직하게 큰 것」이고 그게 대부분이다.
    """

    def __init__(self, app: object, *, max_bytes: int) -> None:
        super().__init__(app)  # pyright: ignore[reportArgumentType]
        self._max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        raw = request.headers.get("content-length")
        if raw is not None:
            try:
                declared = int(raw)
            except ValueError:
                declared = 0
            if declared > self._max_bytes:
                logger.warning(
                    "본문이 너무 커서 받지 않음 path=%s declared=%d",
                    request.url.path,
                    declared,
                )
                return JSONResponse(
                    status_code=413,
                    content=error_body(
                        ErrorCode.VALIDATION_ERROR, "파일이 너무 큽니다."
                    ),
                )
        return await call_next(request)
