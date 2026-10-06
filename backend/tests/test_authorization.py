"""면접관 API 의 로그인 · 주인 검사와 입장 역할 검증 (#130).

`client` 는 `owner` 로 로그인해 있다. 요청에 `ANON` 을 실으면 로그인하지 않은 요청,
`other` 를 실으면 다른 면접관의 요청이 된다.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ErrorCode
from tests.conftest import ANON, FakeMedia

V1 = "/api/v1"


@pytest.fixture
def ids(client: TestClient, session_id: str) -> dict[str, str]:
    """주인이 만든 면접 · 세션 · 컨텍스트 id."""
    interview_id = client.get(f"{V1}/sessions/{session_id}").json()["interviewId"]
    context_id = client.get(f"{V1}/contexts/current").json()["id"]
    return {"interview": interview_id, "session": session_id, "context": context_id}


#: 면접관만 부르는 라우트. `{interview}` 같은 자리는 `ids` 로 채운다.
OWNER_ONLY = [
    ("post", "/interviews"),
    ("get", "/interviews/{interview}"),
    ("post", "/interviews/{interview}/sessions"),
    ("get", "/interviews/{interview}/review"),
    ("patch", "/interviews/{interview}"),
    ("post", "/sessions/{session}/start"),
    ("post", "/sessions/{session}/end"),
    ("get", "/sessions/{session}/summary"),
    ("get", "/contexts/current"),
    ("get", "/contexts/{context}"),
    ("patch", "/contexts/{context}"),
    ("delete", "/contexts/{context}/docs/doc_x"),
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
        ("patch", "/interviews/{interview}", ErrorCode.INTERVIEW_NOT_FOUND),
        ("post", "/sessions/{session}/start", ErrorCode.SESSION_NOT_FOUND),
        ("post", "/sessions/{session}/end", ErrorCode.SESSION_NOT_FOUND),
        ("get", "/sessions/{session}/summary", ErrorCode.SESSION_NOT_FOUND),
        ("get", "/contexts/{context}", ErrorCode.NOT_FOUND),
        ("patch", "/contexts/{context}", ErrorCode.NOT_FOUND),
        ("delete", "/contexts/{context}/docs/doc_x", ErrorCode.NOT_FOUND),
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


def test_each_user_gets_their_own_context(
    client: TestClient, other: dict[str, str]
) -> None:
    mine = client.get(f"{V1}/contexts/current").json()["id"]
    theirs = client.get(f"{V1}/contexts/current", headers=other).json()["id"]

    assert mine != theirs
    assert client.get(f"{V1}/contexts/current").json()["id"] == mine


# ── 입장 역할 ───────────────────────────────────────────


def _join(client: TestClient, session_id: str, role: str, headers: dict[str, str]):
    return client.post(
        f"{V1}/sessions/{session_id}/join", json={"role": role}, headers=headers
    )


@pytest.mark.parametrize(
    ("who", "role", "status"),
    [
        ("anon", "CANDIDATE", 200),
        ("other", "CANDIDATE", 200),
        ("owner", "CANDIDATE", 200),
        ("owner", "INTERVIEWER", 200),
        ("anon", "INTERVIEWER", 401),
        ("other", "INTERVIEWER", 403),
    ],
)
def test_join_role_matrix(
    client: TestClient,
    session_id: str,
    other: dict[str, str],
    who: str,
    role: str,
    status: int,
) -> None:
    headers = {"anon": ANON, "other": other, "owner": {}}[who]

    got = _join(client, session_id, role, headers)

    assert got.status_code == status
    if status == 403:
        assert got.json()["error"]["code"] == ErrorCode.ROLE_NOT_ALLOWED


@pytest.mark.parametrize("token", ["Bearer garbage", "Bearer "])
def test_bad_token_still_joins_as_candidate(
    client: TestClient, session_id: str, token: str
) -> None:
    """만료 · 위조 토큰을 쥐고 초대 링크를 연 사람도 지원자로는 들어온다."""
    headers = {"Authorization": token}

    assert _join(client, session_id, "CANDIDATE", headers).status_code == 200
    assert _join(client, session_id, "INTERVIEWER", headers).status_code == 401


def test_role_is_checked_before_room_state(
    client: TestClient, session_id: str, other: dict[str, str], media: FakeMedia
) -> None:
    """정원 · 종료보다 역할을 먼저 본다 — 권한 없는 요청이 LiveKit 까지 가지 않게."""
    media.participants = 99

    assert _join(client, session_id, "INTERVIEWER", other).status_code == 403

    client.post(f"{V1}/sessions/{session_id}/end")
    assert _join(client, session_id, "INTERVIEWER", other).status_code == 403
