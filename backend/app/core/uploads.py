"""업로드 파일을 받을 때 공통으로 하는 것.

기업 컨텍스트 문서와 지원자 이력서가 같은 규칙을 쓴다. 한쪽만 고치면 조용히
갈라지는 종류라 한곳에 둔다.

크기 선검사는 여기 없다. `BodySizeLimitMiddleware` 가 한다 — `file: UploadFile =
File()` 이 있으면 FastAPI 가 핸들러에 들어가기 전에 multipart 를 전부 파싱하므로,
라우터나 이 함수에서 헤더를 봐도 이미 본문을 다 받은 뒤다.
"""

import unicodedata

from fastapi import UploadFile

from app.core.errors import ApiError, ErrorCode
from app.domain.models import DocKind

#: 업로드 상한. FE 가 이 값을 전제로 진행률 표시를 XHR 로 구현해 뒀다.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

#: multipart 의 경계·헤더가 본문에 더 붙는다. 넉넉히 잡아 미들웨어의 선검사가 정상
#: 업로드를 막지 않게 한다 — 정확한 크기는 본문을 읽은 뒤에 다시 본다.
MULTIPART_SLACK_BYTES = 64 * 1024

#: 파일명 길이 상한. 저장소를 S3 로 옮기면 키 길이가 된다.
MAX_NAME_CHARS = 255

#: 확장자 → 형식. FE 의 `DocKind` 와 같은 둘만 받는다.
KIND_BY_SUFFIX = {".pdf": DocKind.PDF, ".docx": DocKind.DOCX}


def normalized_name(raw: str | None) -> str:
    """업로드 파일명을 저장할 형태로 다듬는다.

    **NFC 로 정규화한다.** macOS 앱이 만든 파일명은 NFD 라, 그대로 두면 눈에는 같아
    보이는데 바이트가 달라 검색·중복 제거·정렬이 조용히 어긋난다. 브라우저는
    파일시스템에 있는 이름을 그대로 실어 보내므로 받는 쪽에서 맞춰야 한다.

    경로 구분자는 지운다. 이름을 그대로 파일 경로로 쓰지는 않지만, 나중에 저장소를
    S3 로 옮기면 그게 키의 일부가 된다.
    """
    name = unicodedata.normalize("NFC", (raw or "").strip())
    name = name.replace("/", "_").replace("\\", "_")
    # 제어문자를 지운다. 널 바이트가 그대로 들어가면 psycopg 가 거부해 500 이 나고,
    # 인메모리 구현은 그냥 받아서 두 저장소가 갈린다.
    name = "".join(ch for ch in name if ch.isprintable())
    if len(name) <= MAX_NAME_CHARS:
        return name
    # 길이로 자르기 전에 확장자를 떼어 둔다. 뒤에서 자르면 확장자가 잘려 나가
    # 멀쩡한 PDF 가 415 를 맞는다. 받는 형식의 확장자만 지키면 된다 — 나머지는
    # 어차피 415 다.
    dot = name.rfind(".")
    suffix = name[dot:] if dot > 0 and name[dot:].lower() in KIND_BY_SUFFIX else ""
    return name[: MAX_NAME_CHARS - len(suffix)] + suffix


async def read_upload(file: UploadFile) -> tuple[str, DocKind, bytes]:
    """이름을 다듬고 형식·크기를 본 뒤 본문을 돌려준다.

    FE 도 보내기 전에 형식과 크기를 거르지만(`UploadRejection`), 그건 편의이지
    경계가 아니다. 여기서 다시 본다.
    """
    name = normalized_name(file.filename)
    if not name:
        raise ApiError(ErrorCode.VALIDATION_ERROR, 422, "파일 이름이 없습니다.")

    suffix = name[name.rfind(".") :].lower() if "." in name else ""
    kind = KIND_BY_SUFFIX.get(suffix)
    if kind is None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, 415, "PDF 와 DOCX 만 올릴 수 있습니다."
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ApiError(ErrorCode.VALIDATION_ERROR, 413, "파일이 너무 큽니다.")
    if not content:
        raise ApiError(ErrorCode.VALIDATION_ERROR, 422, "빈 파일입니다.")

    return name, kind, content
