from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse, summary="서버 상태 확인")
def health_check() -> HealthResponse:
    """LB·컨테이너 오케스트레이터가 부르는 생존 확인용.

    버전과 무관하므로 `/api/v1` prefix 밖에 둔다.
    """
    return HealthResponse(status="ok")
