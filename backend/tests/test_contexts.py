"""기업 컨텍스트 — FE 가 목으로 돌리던 경로들.

FE 의 `api/context.ts` · `api/contextSettings.ts` 가 부르는 모양 그대로 본다.
우리가 편한 모양으로 바꿔 쓰면 붙는지를 보는 의미가 없다.
"""

import unicodedata

import pytest
from fastapi.testclient import TestClient

V1 = "/api/v1"
PDF = b"%PDF-1.7\nfake\n"


@pytest.fixture
def context_id(client: TestClient) -> str:
    made = client.post(f"{V1}/contexts", json={"interviewerId": "user_123"})
    assert made.status_code == 201
    return made.json()["id"]


def upload(client: TestClient, context_id: str, name: str, body: bytes = PDF):
    return client.post(
        f"{V1}/contexts/{context_id}/docs",
        files={"file": (name, body, "application/pdf")},
    )


# ── 생성 ────────────────────────────────────────────────


def test_create_returns_fe_shape(client: TestClient) -> None:
    got = client.post(f"{V1}/contexts", json={"interviewerId": "user_123"})
    assert got.status_code == 201
    body = got.json()
    # FE 의 CompanyContext + talentProfile.
    assert set(body) == {"id", "company", "team", "role", "talentProfile", "docs"}
    assert body["docs"] == []


def test_create_is_idempotent_per_interviewer(client: TestClient) -> None:
    """설정 화면에 들어올 때마다 부르는 자리다. 두 번 불러 둘이 생기면 안 된다."""
    first = client.post(f"{V1}/contexts", json={"interviewerId": "user_123"}).json()
    second = client.post(f"{V1}/contexts", json={"interviewerId": "user_123"}).json()
    assert first["id"] == second["id"]


def test_different_interviewers_get_different_contexts(client: TestClient) -> None:
    a = client.post(f"{V1}/contexts", json={"interviewerId": "user_a"}).json()
    b = client.post(f"{V1}/contexts", json={"interviewerId": "user_b"}).json()
    assert a["id"] != b["id"]


# ── 조회·수정 ───────────────────────────────────────────


def test_get_unknown_context_is_404(client: TestClient) -> None:
    assert client.get(f"{V1}/contexts/ctx_없는것").status_code == 404


def test_patch_updates_only_given_fields(client: TestClient, context_id: str) -> None:
    client.patch(
        f"{V1}/contexts/{context_id}",
        json={"company": "카카오", "role": "백엔드", "talentProfile": "협업"},
    )
    client.patch(f"{V1}/contexts/{context_id}", json={"team": "플랫폼"})
    got = client.get(f"{V1}/contexts/{context_id}").json()
    assert got["company"] == "카카오"
    assert got["role"] == "백엔드"
    assert got["team"] == "플랫폼"


def test_talent_profile_survives_a_reread(client: TestClient, context_id: str) -> None:
    """FE 가 「새로 고치면 빈 칸에서 시작한다」고 적어 둔 그 문제다."""
    client.patch(f"{V1}/contexts/{context_id}", json={"talentProfile": "끈기"})
    assert client.get(f"{V1}/contexts/{context_id}").json()["talentProfile"] == "끈기"


def test_patch_unknown_context_is_404(client: TestClient) -> None:
    got = client.patch(f"{V1}/contexts/ctx_없는것", json={"company": "x"})
    assert got.status_code == 404


# ── 문서 업로드 ─────────────────────────────────────────


def test_upload_returns_fe_doc_shape(client: TestClient, context_id: str) -> None:
    got = upload(client, context_id, "jd.pdf")
    assert got.status_code == 201
    body = got.json()
    assert set(body) == {"id", "name", "kind", "sizeBytes", "status"}
    assert body["kind"] == "pdf"
    assert body["sizeBytes"] == len(PDF)
    # 파싱이 아직 없어 올라온 즉시 ready 다.
    assert body["status"] == "ready"


def test_uploaded_doc_appears_in_the_context(
    client: TestClient, context_id: str
) -> None:
    upload(client, context_id, "jd.pdf")
    upload(client, context_id, "회사소개.docx")
    docs = client.get(f"{V1}/contexts/{context_id}").json()["docs"]
    assert [d["name"] for d in docs] == ["jd.pdf", "회사소개.docx"]


def test_filename_is_normalized_to_nfc(client: TestClient, context_id: str) -> None:
    """macOS 앱이 만든 파일명은 NFD 다. 그대로 두면 검색·중복 제거가 어긋난다."""
    nfc = "이력서.pdf"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc

    upload(client, context_id, nfd)
    stored = client.get(f"{V1}/contexts/{context_id}").json()["docs"][0]["name"]
    assert stored == nfc


@pytest.mark.parametrize("name", ["notes.txt", "sheet.xlsx", "noext"])
def test_unsupported_type_is_415(
    client: TestClient, context_id: str, name: str
) -> None:
    assert upload(client, context_id, name).status_code == 415


def test_too_large_is_413(client: TestClient, context_id: str) -> None:
    from app.api.v1.contexts import MAX_UPLOAD_BYTES

    big = b"%PDF-" + b"x" * MAX_UPLOAD_BYTES
    assert upload(client, context_id, "big.pdf", big).status_code == 413


def test_empty_file_is_422(client: TestClient, context_id: str) -> None:
    assert upload(client, context_id, "empty.pdf", b"").status_code == 422


def test_upload_to_unknown_context_is_404(client: TestClient) -> None:
    assert upload(client, "ctx_없는것", "jd.pdf").status_code == 404


# ── 문서 삭제 ───────────────────────────────────────────


def test_delete_removes_the_doc(client: TestClient, context_id: str) -> None:
    doc_id = upload(client, context_id, "jd.pdf").json()["id"]
    assert client.delete(f"{V1}/contexts/{context_id}/docs/{doc_id}").status_code == 204
    assert client.get(f"{V1}/contexts/{context_id}").json()["docs"] == []


def test_delete_unknown_doc_is_404(client: TestClient, context_id: str) -> None:
    got = client.delete(f"{V1}/contexts/{context_id}/docs/doc_없는것")
    assert got.status_code == 404


def test_delete_is_scoped_to_its_context(client: TestClient) -> None:
    """남의 컨텍스트 문서를 id 만 알면 지울 수 있으면 안 된다."""
    mine = client.post(f"{V1}/contexts", json={"interviewerId": "user_a"}).json()["id"]
    yours = client.post(f"{V1}/contexts", json={"interviewerId": "user_b"}).json()["id"]
    doc_id = upload(client, yours, "jd.pdf").json()["id"]

    assert client.delete(f"{V1}/contexts/{mine}/docs/{doc_id}").status_code == 404
    assert len(client.get(f"{V1}/contexts/{yours}").json()["docs"]) == 1
