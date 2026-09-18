from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.domain import store as store_module


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """저장소를 고른다.

    `DATABASE_URL` 이 없으면 인메모리로 둔다 — 로컬 개발과 테스트가 DB 없이
    돌아야 하고, 지금은 컨테이너 밖에서 띄우는 일이 더 많다.

    스키마 적용을 여기서 한다. 테이블이 둘뿐이고 DDL 이 전부
    `IF NOT EXISTS` 라 기동할 때마다 돌려도 안전하다. 컬럼을 바꿔야 할 때가
    오면 Alembic 을 넣고 이 호출을 걷어낸다.
    """
    if not settings.database_url:
        yield
        return

    from app.infra.postgres import PostgresStore

    postgres = PostgresStore(settings.database_url)
    postgres.open()
    postgres.create_schema()
    store_module.store = postgres
    try:
        yield
    finally:
        postgres.close()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
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
