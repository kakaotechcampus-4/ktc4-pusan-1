from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.config import settings
from app.core.errors import register_error_handlers

app = FastAPI(
    title=settings.app_name,
)

# FE 는 :5173, BE 는 :8000 이라 이게 없으면 브라우저가 요청을 막는다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

# /health 만 prefix 밖이다. 나머지는 전부 settings.api_prefix 아래로 들어간다.
app.include_router(health_router)
app.include_router(v1_router, prefix=settings.api_prefix)
