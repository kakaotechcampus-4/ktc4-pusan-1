"""문서 본문 추출 (#143) — Elice ML API 의 Helpy Document Vision.

JD 와 이력서 PDF 를 평문으로 바꿔 둔다. 그 본문을 읽는 것은 AI Agent 다.

    POST {base}/v1/documents      multipart(document, configs) → {job_id, status}
    GET  {base}/v1/jobs/{job_id}  → {status, result} (queued → running → succeeded)

**결과는 한 번만 받을 수 있다.** `succeeded` 를 한 번 돌려준 뒤로는 같은 job 을
물으면 `{"found": false}` 다 (2026-10-04 실측). 그래서 폴링이 `succeeded` 를 본
그 응답에서 바로 본문을 꺼낸다 — 다시 묻지 않는다.

**응답의 `log` 는 쓰지 않는다.** 처리 과정을 적어 주는 필드인데 문서 본문이 그대로
들어 있다 (`Reading text 1/6: ...`). 로그에는 job id 와 상태만 남긴다.

HTTP 는 카카오 연동과 같이 stdlib 로 부른다. multipart 한 번과 GET 몇 번이 전부라
클라이언트 라이브러리를 들일 이유가 없다. 업로드 응답과 분리된 백그라운드에서
돌고(`BackgroundTasks`), 스레드풀이라 이벤트 루프를 막지 않는다.
"""

import json
import logging
import time
import unicodedata
from collections.abc import Callable
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30
_POLL_SECONDS = 2.0

#: 이미지 설명·차트 변환을 끈다. 필요한 건 글자뿐이라 빨라지고, 이력서 증명사진에
#: 「안경을 쓴 남성」 같은 설명이 붙어 지원자 외모가 AI 입력에 섞이는 것도 막는다.
_CONFIGS = json.dumps({"do_image_description": False, "do_chart_conversion": False})

#: 본문이 아닌 요소. 쪽 번호·머리말이 문단 사이에 끼면 AI 가 그것까지 읽는다.
_SKIPPED_LABELS = frozenset({"header", "footer", "page_number"})

_PENDING = frozenset({"queued", "running"})


class DocumentParser(Protocol):
    def extract_text(self, name: str, content: bytes) -> str | None:
        """PDF 본문을 평문으로 돌려준다. 어떤 이유로든 못 뽑으면 None.

        수 초에서 수십 초가 걸린다. 요청 안에서 부르지 말고 백그라운드에서 부른다.
        """
        ...


def to_text(result: dict[str, Any]) -> str | None:
    """Helpy 의 계층적 JSON 을 읽는 순서대로 이어 붙인다. 본문이 없으면 None.

    표는 HTML 그대로 둔다(`content_compact` 는 스타일을 뺀 것). LLM 은 HTML 표를
    잘 읽고, 평문으로 풀면 행·열 관계가 사라진다.
    """
    lines = [
        element.get("content_compact") or element.get("content") or ""
        for page in result.get("pages", [])
        for element in page.get("elements", [])
        if element.get("label") not in _SKIPPED_LABELS
    ]
    # NUL 은 PostgreSQL TEXT 가 거부한다. 파일명과 같은 이유로 NFC 로 맞춘다.
    text = unicodedata.normalize(
        "NFC", "\n".join(line.strip() for line in lines if line.strip())
    ).replace("\x00", "")
    return text or None


def _multipart(name: str, content: bytes) -> tuple[bytes, str]:
    boundary = uuid4().hex
    quoted = name.replace('"', "_")
    body = b"".join(
        [
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="{quoted}"\r\n'
            "Content-Type: application/pdf\r\n\r\n".encode(),
            content,
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="configs"\r\n\r\n'
            f"{_CONFIGS}\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


class HelpyDocumentParser:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout_seconds
        self._sleep = sleep
        self._clock = clock

    def _call(self, path: str, body: bytes | None = None, ctype: str = "") -> Any:
        headers = {"Authorization": f"Bearer {self._key}"}
        if ctype:
            headers["Content-Type"] = ctype
        request = Request(f"{self._base}{path}", data=body, headers=headers)
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())

    def extract_text(self, name: str, content: bytes) -> str | None:
        if not (self._base and self._key):
            logger.warning(
                "ELICE_API_KEY·HELPY_DOC_BASE_URL 이 없어 본문을 뽑지 않습니다."
            )
            return None
        try:
            job_id = self._call("/v1/documents", *_multipart(name, content))["job_id"]
            deadline = self._clock() + self._timeout
            while True:
                job = self._call(f"/v1/jobs/{job_id}")
                status = job.get("status")
                if status == "succeeded":
                    return to_text(job.get("result") or {})
                if status not in _PENDING:
                    # `found: false` 도 여기로 온다. 상태값만 남긴다 —
                    # 응답의 log 에 본문이 있다.
                    logger.warning("문서 추출 실패 job_id=%s status=%s", job_id, status)
                    return None
                if self._clock() >= deadline:
                    logger.warning("문서 추출 시간 초과 job_id=%s", job_id)
                    return None
                self._sleep(_POLL_SECONDS)
        except HTTPError as exc:
            # 본문은 남기지 않는다. 우리가 보낸 문서 일부가 섞여 돌아올 수 있다.
            logger.warning("Helpy 응답 %s", exc.code)
        except (URLError, TimeoutError, ValueError, KeyError) as exc:
            logger.warning("Helpy 호출 실패: %s", type(exc).__name__)
        return None


def check_key_at_startup() -> None:
    """`check_secret_at_startup` 과 같은 규칙이다. 로컬은 경고, 운영은 기동 거부."""
    if settings.elice_api_key and settings.helpy_doc_base_url:
        return
    if settings.app_env == "production":
        raise RuntimeError(
            "ELICE_API_KEY·HELPY_DOC_BASE_URL 이 비어 있습니다. 운영에서는 올린 "
            "JD·이력서가 전부 failed 가 되므로 기동하지 않습니다."
        )
    logger.warning(
        "ELICE_API_KEY·HELPY_DOC_BASE_URL 이 비어 있어 문서가 failed 로 끝납니다."
    )


parser: DocumentParser = HelpyDocumentParser(
    base_url=settings.helpy_doc_base_url,
    api_key=settings.elice_api_key,
    timeout_seconds=settings.doc_parse_timeout_seconds,
)
