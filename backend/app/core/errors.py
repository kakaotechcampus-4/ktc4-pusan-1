"""공통 에러 응답 — 테크스펙 §2.

모든 실패 응답은 형태가 하나다. `message` 는 화면에 그대로 노출하지 않으며
클라이언트는 `code` 로 분기한다.

    { "error": { "code": "...", "message": "...", "retryable": false } }

FE `api/client.ts` 가 이미 `body?.error?.code` 로 파싱하고 있다.
"""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    """클라이언트가 분기에 쓰는 값. 추가만 하고 기존 값은 바꾸지 않는다."""

    # 공통
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # 면접 · 세션
    INTERVIEW_NOT_FOUND = "INTERVIEW_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_ENDED = "SESSION_ENDED"
    INVALID_SESSION_STATE = "INVALID_SESSION_STATE"
    ROOM_FULL = "ROOM_FULL"


class ApiError(Exception):
    """도메인 실패. 라우터에서 raise 하면 아래 핸들러가 규격 응답으로 바꾼다."""

    def __init__(
        self,
        code: ErrorCode | str,
        status_code: int,
        message: str = "",
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message or str(code))
        self.code = str(code)
        self.status_code = status_code
        self.message = message or str(code)
        self.retryable = retryable


def error_body(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def _api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, retryable=exc.retryable),
    )


def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """422 를 공통 포맷으로 바꾼다.

    FastAPI 기본 응답은 `detail` 배열이라 규격에 안 맞는다.
    """
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content=error_body(ErrorCode.VALIDATION_ERROR, "요청 값이 올바르지 않습니다."),
    )


def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """라우팅 404·405 등 Starlette 가 직접 던지는 것도 같은 포맷으로 맞춘다."""
    assert isinstance(exc, StarletteHTTPException)
    code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, str(exc.detail)),
    )


class ErrorDetail(BaseModel):
    # ErrorCode 로 선언해야 OpenAPI 에 값 목록이 실린다. str 로 두면 Swagger 를 봐도
    # 어떤 코드가 오는지 알 수 없어서 클라이언트가 status 로만 분기하게 된다.
    code: ErrorCode
    message: str
    retryable: bool = False


class ErrorResponse(BaseModel):
    """OpenAPI 문서용. 실제 직렬화는 error_body() 가 한다."""

    error: ErrorDetail


def responses(*statuses: tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    """명세 Status 표를 그대로 Swagger 에 싣는다.

    responses((404, "Session을 찾을 수 없음"), (409, "..."))
    """
    return {
        code: {"description": description, "model": ErrorResponse}
        for code, description in statuses
    }


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
