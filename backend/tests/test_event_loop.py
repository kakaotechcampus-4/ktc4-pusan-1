"""async 라우트가 저장소를 이벤트 루프 밖에서 부르는지 (#133).

저장소는 동기라 이벤트 루프에서 부르면 그동안 같은 프로세스의 다른 요청(전사 수신 ·
webhook · 입장)이 줄을 선다. 스레드풀로 넘겼으면 그 스레드에는 돌고 있는 루프가 없다.
"""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.store import InMemoryStore

V1 = "/api/v1"
PDF = ("cv.pdf", b"%PDF-1.4", "application/pdf")


def _spy(name: str, method: Callable[..., Any], on_loop: list[str]) -> Callable:
    def spy(*args: Any, **kwargs: Any) -> Any:
        try:
            asyncio.get_running_loop()
            on_loop.append(name)
        except RuntimeError:
            pass
        return method(*args, **kwargs)

    return spy


@pytest.fixture
def on_loop(store: InMemoryStore, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """이벤트 루프 위에서 불린 저장소 메서드 이름."""
    called: list[str] = []
    for name in dir(store):
        method = getattr(store, name)
        if not name.startswith("_") and callable(method):
            monkeypatch.setattr(store, name, _spy(name, method, called))
    return called


def test_async_routes_keep_the_store_off_the_event_loop(
    client: TestClient, session_id: str, on_loop: list[str]
) -> None:
    interview_id = client.get(f"{V1}/sessions/{session_id}").json()["interviewId"]
    context_id = client.get(f"{V1}/contexts/current").json()["id"]

    calls = [
        client.post(f"{V1}/interviews/{interview_id}/sessions"),
        client.post(f"{V1}/interviews/{interview_id}/resume", files={"file": PDF}),
        client.post(f"{V1}/contexts/{context_id}/docs", files={"file": PDF}),
        client.post(f"{V1}/sessions/{session_id}/join", json={}),
        client.post(f"{V1}/sessions/{session_id}/end"),
    ]

    assert [c.status_code for c in calls] == [201, 201, 201, 200, 200]
    assert on_loop == []
