"""면접관 API 의 로그인 · 주인 검사 (#130).

`client` 는 `owner` 로 로그인해 있다. 요청에 `ANON` 을 실으면 로그인하지 않은 요청,
`other` 를 실으면 다른 면접관의 요청이 된다.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ErrorCode
from tests.conftest import ANON

V1 = "/api/v1"


@pytest.fixture
def ids(client: TestClient, session_id: str) -> dict[str, str]:
    """주인이 만든 면접 · 세션 id."""
    interview_id = client.get(f"{V1}/sessions/{session_id}").json()["interviewId"]
    return {"interview": interview_id, "session": session_id}


#: 면접관만 부르는 라우트. `{interview}` 같은 자리는 `ids` 로 채운다.
OWNER_ONLY = [
    ("post", "/interviews"),
    ("get", "/interviews/{interview}"),
    ("post", "/interviews/{interview}/sessions"),
    ("get", "/interviews/{interview}/review"),
    ("post", "/sessions/{session}/start"),
    ("post", "/sessions/{session}/end"),
    ("get", "/sessions/{session}/summary"),
]


def _call(client: TestClient, method: str, path: str, headers: dict[str, str]):
    url = f"{V1}{path}"
    if method in ("post", "patch"):
        return client.request(method, url, json={}, headers=headers)
    return client.request(method, url, headers=headers)


@pytest.mark.parametrize(("method", "path"), OWNER_ONLY)
def test_owner_only_routes_need_login(
    client: TestClient, ids: dict[str, str], method: str, path: str
) -> None:
    got = _call(client, method, path.format(**ids), ANON)

    assert got.status_code == 401
    assert got.json()["error"]["code"] == ErrorCode.UNAUTHORIZED


@pytest.mark.parametrize(
    ("method", "path", "code"),
    [
        ("get", "/interviews/{interview}", ErrorCode.INTERVIEW_NOT_FOUND),
        ("post", "/interviews/{interview}/sessions", ErrorCode.INTERVIEW_NOT_FOUND),
        ("get", "/interviews/{interview}/review", ErrorCode.INTERVIEW_NOT_FOUND),
        ("post", "/sessions/{session}/start", ErrorCode.SESSION_NOT_FOUND),
        ("post", "/sessions/{session}/end", ErrorCode.SESSION_NOT_FOUND),
        ("get", "/sessions/{session}/summary", ErrorCode.SESSION_NOT_FOUND),
    ],
)
def test_someone_elses_resource_looks_missing(
    client: TestClient,
    ids: dict[str, str],
    other: dict[str, str],
    method: str,
    path: str,
    code: ErrorCode,
) -> None:
    """남의 것도 없는 것과 같은 404 · 같은 코드다 — 다르면 id 가 있다는 게 드러난다."""
    theirs = _call(client, method, path.format(**ids), other)
    missing = _call(
        client,
        method,
        path.format(interview="int_x", session="ses_x", context="ctx_x"),
        other,
    )

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json()["error"]["code"] == missing.json()["error"]["code"] == code


def test_resume_upload_is_owner_only(
    client: TestClient, ids: dict[str, str], other: dict[str, str]
) -> None:
    files = {"file": ("cv.pdf", b"%PDF-1.4", "application/pdf")}
    url = f"{V1}/interviews/{ids['interview']}/resume"

    assert client.post(url, files=files, headers=ANON).status_code == 401
    assert client.post(url, files=files, headers=other).status_code == 404
