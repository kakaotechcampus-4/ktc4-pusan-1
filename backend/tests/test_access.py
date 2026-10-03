"""누가 무엇을 부를 수 있나 (#144).

면접관 API 는 로그인이 필요하고, 남의 것은 없는 것과 똑같이 404 다. 지원자가 쓰는
경로(지원자 join · 세션 상태 조회)만 로그인 없이 열린다.
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ANON

V1 = "/api/v1"
PDF = {"file": ("이력서.pdf", b"%PDF-1.7\n", "application/pdf")}


def _routes(interview_id: str, session_id: str, context_id: str):
    """(method, path, 요청 인자, 남의 것일 때 코드)."""
    i, s, c = interview_id, session_id, context_id
    return [
        ("get", f"{V1}/interviews/{i}", {}, "INTERVIEW_NOT_FOUND"),
        ("post", f"{V1}/interviews/{i}/sessions", {}, "INTERVIEW_NOT_FOUND"),
        ("get", f"{V1}/interviews/{i}/review", {}, "INTERVIEW_NOT_FOUND"),
        ("post", f"{V1}/interviews/{i}/resume", {"files": PDF}, "INTERVIEW_NOT_FOUND"),
        ("post", f"{V1}/sessions/{s}/start", {}, "SESSION_NOT_FOUND"),
        ("post", f"{V1}/sessions/{s}/end", {}, "SESSION_NOT_FOUND"),
        ("get", f"{V1}/sessions/{s}/summary", {}, "SESSION_NOT_FOUND"),
        (
            "post",
            f"{V1}/sessions/{s}/join",
            {"json": {"role": "INTERVIEWER"}},
            "SESSION_NOT_FOUND",
        ),
        ("get", f"{V1}/contexts/{c}", {}, "NOT_FOUND"),
        ("patch", f"{V1}/contexts/{c}", {"json": {"company": "x"}}, "NOT_FOUND"),
        ("post", f"{V1}/contexts/{c}/docs", {"files": PDF}, "NOT_FOUND"),
        ("delete", f"{V1}/contexts/{c}/docs/doc_x", {}, "NOT_FOUND"),
    ]


@pytest.fixture
def routes(client: TestClient, session_id: str):
    interview_id = client.get(f"{V1}/sessions/{session_id}").json()["interviewId"]
    context_id = client.get(f"{V1}/contexts/current").json()["id"]
    return _routes(interview_id, session_id, context_id)


def test_interviewer_routes_need_login(client: TestClient, routes):
    for method, path, kwargs, _ in routes:
        response = client.request(method, path, headers=ANON, **kwargs)
        assert response.status_code == 401, (method, path)
        assert response.json()["error"]["code"] == "UNAUTHORIZED"

    for path in (f"{V1}/interviews", f"{V1}/contexts/current"):
        assert client.get(path, headers=ANON).status_code == 401
    assert client.post(f"{V1}/interviews", json={}, headers=ANON).status_code == 401


def test_someone_elses_resources_are_404(
    client: TestClient, routes, other: dict[str, str]
):
    for method, path, kwargs, code in routes:
        response = client.request(method, path, headers=other, **kwargs)
        assert response.status_code == 404, (method, path)
        assert response.json()["error"]["code"] == code


def test_candidate_paths_stay_open(client: TestClient, session_id: str):
    """지원자는 계정이 없다. 초대 링크의 sessionId 만으로 들어오고 상태를 본다."""
    joined = client.post(
        f"{V1}/sessions/{session_id}/join", json={"role": "CANDIDATE"}, headers=ANON
    )
    state = client.get(f"{V1}/sessions/{session_id}", headers=ANON)

    assert joined.status_code == 200
    assert state.status_code == 200


def test_owner_joins_as_interviewer(client: TestClient, session_id: str):
    response = client.post(
        f"{V1}/sessions/{session_id}/join", json={"role": "INTERVIEWER"}
    )

    assert response.status_code == 200


def test_each_interviewer_has_their_own_context(
    client: TestClient, other: dict[str, str]
):
    mine = client.get(f"{V1}/contexts/current").json()
    client.patch(f"{V1}/contexts/{mine['id']}", json={"company": "카카오"})

    theirs = client.get(f"{V1}/contexts/current", headers=other).json()

    assert theirs["id"] != mine["id"]
    assert theirs["company"] == ""
