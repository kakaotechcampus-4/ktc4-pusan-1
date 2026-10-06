"""Helpy Document Vision 연동 (#143).

실제 서버는 부르지 않는다. 응답 모양은 2026-10-04 에 받은 실제 응답을
`fixtures/helpy_job_succeeded.json` 에 그대로 두고 쓴다.
"""

import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from app.services import documents
from app.services.documents import HelpyDocumentParser, to_text

SUCCEEDED = json.loads(
    (Path(__file__).parent / "fixtures" / "helpy_job_succeeded.json").read_text()
)


def test_to_text_keeps_reading_order_and_compact_tables():
    text = to_text(SUCCEEDED["result"])

    assert text is not None
    assert text.splitlines()[:3] == [
        "누리뱅크 백엔드 신입 채용",
        "플랫폼팀에서 상품 조회·주문 API를 개발하고 운영합니다.",
        "자격 요건",
    ]
    # 스타일을 뺀 표다. border 가 남으면 LLM 입력만 길어진다.
    assert "<td>근무지</td><td>부산</td>" in text
    assert "border" not in text


def test_to_text_drops_page_furniture_and_nul():
    result = {
        "pages": [
            {
                "elements": [
                    {"label": "header", "content": "ISSN 2288-7083"},
                    {"label": "text", "content": "본문\x00"},
                    {"label": "page_number", "content": "1"},
                    {"label": "picture", "content": None, "description": None},
                ]
            }
        ]
    }

    assert to_text(result) == "본문"


def test_to_text_of_an_empty_document_is_none():
    """스캔이 비었거나 글자가 없는 PDF. 빈 문자열을 ready 로 두지 않는다."""
    assert to_text({"page_count": 1, "pages": [{"elements": []}]}) is None


def _script(monkeypatch: pytest.MonkeyPatch, *replies) -> list:
    """`urlopen` 을 차례대로 답하는 대역으로 바꾸고, 받은 요청을 남긴다."""
    seen = []
    queue = list(replies)

    def fake_urlopen(request, timeout):
        seen.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(documents, "urlopen", fake_urlopen)
    return seen


def _parser(timeout: float = 60) -> HelpyDocumentParser:
    clock = iter(range(0, 10_000, 2))
    return HelpyDocumentParser(
        "https://mlapi.run/uuid/",
        "key",
        timeout,
        sleep=lambda _: None,
        clock=lambda: next(clock),
    )


def test_submits_then_polls_until_succeeded(monkeypatch: pytest.MonkeyPatch):
    seen = _script(
        monkeypatch,
        {"job_id": "job_1", "status": "queued"},
        {"job_id": "job_1", "status": "running"},
        SUCCEEDED,
    )

    text = _parser().extract_text("누리 JD.pdf", b"%PDF-1.7")

    assert text is not None and text.startswith("누리뱅크")
    submit, *polls = seen
    assert submit.full_url == "https://mlapi.run/uuid/v1/documents"
    assert submit.get_header("Authorization") == "Bearer key"
    assert submit.get_header("Content-type").startswith("multipart/form-data")
    body = submit.data
    assert b'name="document"; filename="' in body and b"%PDF-1.7" in body
    # 이미지 설명을 끈다 — 이력서 사진의 외모 묘사가 AI 입력에 섞이면 안 된다.
    assert b'"do_image_description": false' in body
    assert [p.full_url for p in polls] == ["https://mlapi.run/uuid/v1/jobs/job_1"] * 2


@pytest.mark.parametrize(
    "final",
    [
        {"job_id": "job_1", "status": "failed"},
        # 결과는 한 번만 준다. 이미 가져간 job 은 이렇게 온다.
        {"job_id": "job_1", "found": False},
    ],
)
def test_failed_job_is_none(monkeypatch: pytest.MonkeyPatch, final):
    _script(monkeypatch, {"job_id": "job_1", "status": "queued"}, final)

    assert _parser().extract_text("a.pdf", b"x") is None


def test_gives_up_after_the_deadline(monkeypatch: pytest.MonkeyPatch):
    running = {"job_id": "job_1", "status": "running"}
    _script(monkeypatch, {"job_id": "job_1"}, *[running] * 10)

    assert _parser(timeout=5).extract_text("a.pdf", b"x") is None


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("u", 401, "x", {}, io.BytesIO(b"{}")),  # pyright: ignore[reportArgumentType]
        URLError("down"),
        TimeoutError(),
    ],
)
def test_transport_failure_is_none(monkeypatch: pytest.MonkeyPatch, error):
    _script(monkeypatch, error)

    assert _parser().extract_text("a.pdf", b"x") is None


def test_without_key_nothing_is_sent(monkeypatch: pytest.MonkeyPatch):
    seen = _script(monkeypatch)

    assert HelpyDocumentParser("", "", 60).extract_text("a.pdf", b"x") is None
    assert seen == []


def test_production_refuses_to_start_without_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(documents.settings, "app_env", "production")
    monkeypatch.setattr(documents.settings, "elice_api_key", "")

    with pytest.raises(RuntimeError):
        documents.check_key_at_startup()
