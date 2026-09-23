"""API v1 라우터 집합."""

from fastapi import APIRouter

from app.api.v1 import contexts, interviews, sessions, webhooks

router = APIRouter()
router.include_router(contexts.router)
router.include_router(interviews.router)
router.include_router(sessions.router)
# 클라이언트용 API 가 아니다. LiveKit 서버가 부른다.
router.include_router(webhooks.router)
