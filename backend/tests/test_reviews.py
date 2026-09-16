"""면접 기록 조회 — 계약 확정 전 단계.

FE(`types/interview.ts`)가 이미 이 경로를 부르고 `PROCESSING` 분기를 갖고 있다.
BE 는 지금 그 분기만 돌려준다. READY 는 세 파트 합의 전이라 나가지 않는다.
"""

from fastapi.testclient import TestClient


def _interview(client: TestClient) -> str:
    created = client.post("/api/v1/interviews", json={"interviewerId": "user_123"})
    return created.json()["interviewId"]


def test_review_is_processing(client: TestClient):
    interview_id = _interview(client)

    response = client.get(f"/api/v1/interviews/{interview_id}/review")

    # 202 인 건 FE 가 그렇게 읽기 때문이다 — "준비 전에는 202 와 PROCESSING".
    assert response.status_code == 202
    assert response.json() == {"status": "PROCESSING", "etaSec": None}


def test_review_eta_is_empty(client: TestClient):
    """추정할 근거가 없다. 숫자를 주면 FE 가 그걸 믿고 화면에 쓴다."""
    interview_id = _interview(client)

    body = client.get(f"/api/v1/interviews/{interview_id}/review").json()

    assert body["etaSec"] is None


def test_review_of_unknown_interview(client: TestClient):
    response = client.get("/api/v1/interviews/int_nope/review")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INTERVIEW_NOT_FOUND"


def test_ready_shape_is_not_published_yet(client: TestClient):
    """합의 전 형태를 OpenAPI 에 실으면 FE·AI 가 확정된 계약으로 읽는다.

    READY 는 `schemas.py` 에 모델로만 둔다. 합의되면 이 테스트를 뒤집는다.
    """
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert "ReviewProcessingResponse" in schemas
    assert "ReviewReadyResponse" not in schemas
