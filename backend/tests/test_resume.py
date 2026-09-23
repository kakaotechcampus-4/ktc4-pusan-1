"""지원자 이력서 업로드 — FE 의 `api/resume.ts` 가 부르는 경로.

면접 한 건에 한 장이고 다시 올리면 덮어쓴다. FE 가 목록도 삭제도 두지 않은 것이
그 전제다.

형식·크기·이름 정규화는 기업 컨텍스트와 같은 `app/core/uploads.py` 를 쓴다. 그쪽
테스트가 규칙 자체를 보므로 여기서는 이 경로에 실제로 걸리는지만 본다.
"""

import unicodedata

import pytest
from fastapi.testclient import TestClient

from app.domain.store import InMemoryStore

V1 = "/api/v1"
PDF = b"%PDF-1.7\nresume\n"


@pytest.fixture
def interview_id(client: TestClient) -> str:
    made = client.post(f"{V1}/interviews", json={"interviewerId": "user_123"})
    return made.json()["interviewId"]


def upload(client: TestClient, interview_id: str, name: str, body: bytes = PDF):
    return client.post(
        f"{V1}/interviews/{interview_id}/resume",
        files={"file": (name, body, "application/pdf")},
    )


def test_upload_returns_the_fe_doc_shape(client: TestClient, interview_id: str) -> None:
    got = upload(client, interview_id, "이력서.pdf")
    assert got.status_code == 201
    body = got.json()
    # FE 는 기업 컨텍스트 문서와 같은 카드로 그린다.
    assert set(body) == {"id", "name", "kind", "sizeBytes", "status"}
    assert body["kind"] == "pdf"
    assert body["sizeBytes"] == len(PDF)
    assert body["status"] == "ready"


def test_reupload_replaces_the_previous_one(
    client: TestClient, store: InMemoryStore, interview_id: str
) -> None:
    """FE 가 목록도 삭제도 두지 않았다 — 새 이력서를 올리면 앞의 것은 쓸 일이 없다."""
    upload(client, interview_id, "old.pdf")
    upload(client, interview_id, "new.docx", b"PK\x03\x04docx")

    stored = store.get_resume(interview_id)
    assert stored is not None
    assert stored.name == "new.docx"


def test_filename_is_normalized_to_nfc(
    client: TestClient, store: InMemoryStore, interview_id: str
) -> None:
    nfc = "홍길동_이력서.pdf"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc

    upload(client, interview_id, nfd)
    stored = store.get_resume(interview_id)
    assert stored is not None
    assert stored.name == nfc


@pytest.mark.parametrize("name", ["resume.txt", "resume.hwp", "noext"])
def test_unsupported_type_is_415(
    client: TestClient, interview_id: str, name: str
) -> None:
    assert upload(client, interview_id, name).status_code == 415


def test_oversized_body_is_refused_before_it_is_read(
    client: TestClient, interview_id: str
) -> None:
    """이력서 경로도 미들웨어가 앞에서 막는다 — 본문을 안 보내도 413 이 온다."""
    from app.core.uploads import MAX_UPLOAD_BYTES

    got = client.post(
        f"{V1}/interviews/{interview_id}/resume",
        content=b"",
        headers={
            "content-type": "multipart/form-data; boundary=x",
            "content-length": str(MAX_UPLOAD_BYTES * 20),
        },
    )
    assert got.status_code == 413


def test_empty_file_is_422(client: TestClient, interview_id: str) -> None:
    assert upload(client, interview_id, "empty.pdf", b"").status_code == 422


def test_upload_to_unknown_interview_is_404(client: TestClient) -> None:
    assert upload(client, "int_없는것", "이력서.pdf").status_code == 404


def test_resumes_do_not_leak_between_interviews(
    client: TestClient, store: InMemoryStore
) -> None:
    a = client.post(f"{V1}/interviews", json={"interviewerId": "user_a"}).json()[
        "interviewId"
    ]
    b = client.post(f"{V1}/interviews", json={"interviewerId": "user_b"}).json()[
        "interviewId"
    ]
    upload(client, a, "a.pdf")
    assert store.get_resume(b) is None
