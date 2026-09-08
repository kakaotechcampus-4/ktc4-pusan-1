"""API v1 라우터 집합."""

from fastapi import APIRouter

from app.api.v1 import interviews, sessions

router = APIRouter()
router.include_router(interviews.router)
router.include_router(sessions.router)
