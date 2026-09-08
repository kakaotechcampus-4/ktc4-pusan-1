"""라우터 의존성.

라우터는 구현체가 아니라 Protocol 에만 의존한다. 테스트에서
`app.dependency_overrides` 로 갈아끼우고, DB 가 정해지면 여기만 바꾼다.
"""

from typing import Annotated

from fastapi import Depends

from app.domain import store as store_module
from app.domain.store import Store
from app.services import media as media_module
from app.services.media import MediaGateway


def get_store() -> Store:
    return store_module.store


def get_media() -> MediaGateway:
    return media_module.media


StoreDep = Annotated[Store, Depends(get_store)]
MediaDep = Annotated[MediaGateway, Depends(get_media)]
