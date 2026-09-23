"""기업 컨텍스트 — FE 가 목으로 돌리던 경로들.

FE 의 `api/context.ts` · `api/contextSettings.ts` 가 부르는 모양 그대로 본다.
우리가 편한 모양으로 바꿔 쓰면 붙는지를 보는 의미가 없다.
"""

import unicodedata

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Context
from app.domain.store import InMemoryStore

V1 = "/api/v1"
PDF = b"%PDF-1.7\nfake\n"


@pytest.fixture
def context_id(client: TestClient) -> str:
    return client.get(f"{V1}/contexts/current").json()["id"]


def upload(client: TestClient, context_id: str, name: str, body: bytes = PDF):
    return client.post(
        f"{V1}/contexts/{context_id}/docs",
        files={"file": (name, body, "application/pdf")},
    )


# ── 현재 컨텍스트 ───────────────────────────────────────


def test_current_returns_fe_shape(client: TestClient) -> None:
    got = client.get(f"{V1}/contexts/current")
    assert got.status_code == 200
    body = got.json()
    # FE 의 CompanyContext + talentProfile.
    assert set(body) == {"id", "company", "team", "role", "talentProfile", "docs"}
    assert body["docs"] == []


def test_current_is_the_same_context_every_time(client: TestClient) -> None:
    """설정 화면에 들어올 때마다 부르는 자리다. 부를 때마다 새로 생기면 안 된다."""
    first = client.get(f"{V1}/contexts/current").json()["id"]
    second = client.get(f"{V1}/contexts/current").json()["id"]
    assert first == second


def test_current_keeps_what_was_saved(client: TestClient) -> None:
    context_id = client.get(f"{V1}/contexts/current").json()["id"]
    client.patch(f"{V1}/contexts/{context_id}", json={"company": "카카오"})
    assert client.get(f"{V1}/contexts/current").json()["company"] == "카카오"


def test_concurrent_current_calls_make_one_context(client: TestClient) -> None:
    """React StrictMode 나 재시도로 겹쳐 불린다. 확인한 뒤 넣으면 둘이 생긴다."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(
            pool.map(
                lambda _: client.get(f"{V1}/contexts/current").json()["id"], range(8)
            )
        )
    assert len(set(ids)) == 1


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


@pytest.mark.parametrize("suffix", [".pdf", ".DOCX"])
def test_overlong_name_keeps_its_suffix(
    client: TestClient, context_id: str, suffix: str
) -> None:
    """길이로 자를 때 확장자가 잘려 415 가 나면 안 된다."""
    response = upload(client, context_id, "가" * 300 + suffix)
    assert response.status_code == 201
    name = response.json()["name"]
    assert len(name) == 255
    assert name.endswith(suffix)


@pytest.mark.parametrize("name", ["notes.txt", "sheet.xlsx", "noext"])
def test_unsupported_type_is_415(
    client: TestClient, context_id: str, name: str
) -> None:
    assert upload(client, context_id, name).status_code == 415


def test_too_large_is_413(client: TestClient, context_id: str) -> None:
    from app.api.v1.contexts import MAX_UPLOAD_BYTES

    big = b"%PDF-" + b"x" * MAX_UPLOAD_BYTES
    assert upload(client, context_id, "big.pdf", big).status_code == 413


def test_oversized_body_is_refused_before_it_is_read(
    client: TestClient, context_id: str
) -> None:
    """읽은 뒤에 재는 것만으로는 부족하다.

    `file: UploadFile = File()` 이 있으면 **FastAPI 가 핸들러에 들어가기 전에**
    multipart 를 전부 파싱한다. 그래서 핸들러 첫 줄에서 `Content-Length` 를 봐도
    그때는 이미 본문을 다 받은 뒤다 — 1GB 를 선언하고 1KB 만 보내면 서버가 나머지를
    계속 기다리는 것을 실제로 확인했다.

    그래서 검사는 미들웨어에 있다. 여기서는 **본문을 안 보내고도 413 이 오는지**로
    그게 앞에 있다는 걸 잠근다. 라우터 안에서 검사하면 본문을 기다리느라 이 요청은
    답을 못 받는다.
    """
    from app.api.v1.contexts import MAX_UPLOAD_BYTES

    got = client.post(
        f"{V1}/contexts/{context_id}/docs",
        content=b"",
        headers={
            "content-type": "multipart/form-data; boundary=x",
            "content-length": str(MAX_UPLOAD_BYTES * 20),
        },
    )
    assert got.status_code == 413


def test_normal_upload_is_not_blocked_by_the_limit(
    client: TestClient, context_id: str
) -> None:
    """선검사가 정상 업로드를 막으면 안 된다 — multipart 경계·헤더가 더 붙는다."""
    assert upload(client, context_id, "jd.pdf").status_code == 201


def test_control_characters_are_stripped_from_the_name(
    client: TestClient, context_id: str
) -> None:
    """널 바이트가 그대로 들어가면 psycopg 가 거부해 500 이 나고, 인메모리는 그냥
    받아서 두 저장소가 갈린다.

    테스트 클라이언트의 `files=` 는 파일명을 이스케이프하므로 여기서는 multipart
    본문을 직접 만든다 — 진짜 브라우저·라이브러리는 그대로 실어 보낼 수 있다.
    """
    boundary = "----irya"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="a\x00b.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode()
        + PDF
        + f"\r\n--{boundary}--\r\n".encode()
    )

    got = client.post(
        f"{V1}/contexts/{context_id}/docs",
        content=body,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )
    assert got.status_code == 201
    assert got.json()["name"] == "ab.pdf"


def test_patch_rejects_an_overlong_field(client: TestClient, context_id: str) -> None:
    got = client.patch(
        f"{V1}/contexts/{context_id}", json={"talentProfile": "가" * 4001}
    )
    assert got.status_code == 422


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


def test_delete_is_scoped_to_its_context(
    client: TestClient, store: InMemoryStore, context_id: str
) -> None:
    """남의 컨텍스트 문서를 id 만 알면 지울 수 있으면 안 된다."""
    other = store.ensure_context(Context(owner_id="다른조직"))
    doc_id = upload(client, context_id, "jd.pdf").json()["id"]

    assert client.delete(f"{V1}/contexts/{other.id}/docs/{doc_id}").status_code == 404
    assert len(client.get(f"{V1}/contexts/{context_id}").json()["docs"]) == 1
