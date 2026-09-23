"""기업 컨텍스트 — 회사·직무·인재상과 면접에 쓸 문서.

FE 가 develop 때부터 이 경로들을 부르고 있었는데 BE 에 하나도 없어서 목으로만
돌고 있었다 (`frontend/src/api/context.ts`, `contextSettings.ts`).

**면접이 아니라 면접관에게 딸린다.** 회사 정보와 JD 는 면접마다 바뀌지 않으므로
설정에 한 번 넣고 계속 쓴다는 것이 #79 의 제안이고, 그래서 면접관 한 명에 하나다.
`POST /contexts` 는 그래서 멱등하다 — 이미 있으면 그걸 돌려준다. 로그인이 아직
없어서 소유자는 `interviewerId` 로 둔다.

문서 본문 추출(파싱)은 이 범위가 아니다. 누가 하는지가 안 정해졌고(#70 의
「`resume` 가 합의안은 본문 문자열인데 현재는 스토리지 키」), 지금은 올라온 즉시
`ready` 다. `parsing` 상태는 FE 가 이미 갖고 있어 나중에 붙이면 된다.
"""

import unicodedata
from typing import Annotated

from fastapi import APIRouter, File, Path, UploadFile, status

from app.api.deps import StoreDep
from app.core.errors import ApiError, ErrorCode, responses
from app.domain.models import Context, ContextDoc, DocKind
from app.domain.store import Store
from app.schemas import (
    ContextDocResponse,
    ContextResponse,
    CreateContextRequest,
    UpdateContextRequest,
)

router = APIRouter(prefix="/contexts", tags=["기업 컨텍스트"])

ContextIdPath = Annotated[str, Path(alias="contextId")]
DocIdPath = Annotated[str, Path(alias="docId")]

#: 업로드 상한. FE 가 이 값을 전제로 진행률 표시를 XHR 로 구현해 뒀다.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

#: 확장자 → 형식. FE 의 `DocKind` 와 같은 둘만 받는다.
KIND_BY_SUFFIX = {".pdf": DocKind.PDF, ".docx": DocKind.DOCX}


def _load(store: Store, context_id: str) -> Context:
    context = store.get_context(context_id)
    if context is None:
        raise ApiError(ErrorCode.NOT_FOUND, 404, "컨텍스트를 찾을 수 없습니다.")
    return context


def _to_response(store: Store, context: Context) -> ContextResponse:
    return ContextResponse(
        id=context.id,
        company=context.company,
        team=context.team,
        role=context.role,
        talent_profile=context.talent_profile,
        docs=[
            ContextDocResponse(
                id=doc.id,
                name=doc.name,
                kind=doc.kind,
                size_bytes=doc.size_bytes,
                status=doc.status,
            )
            for doc in store.list_docs(context.id)
        ],
    )


def _normalized_name(raw: str | None) -> str:
    """업로드 파일명을 저장할 형태로 다듬는다.

    **NFC 로 정규화한다.** macOS 앱이 만든 파일명은 NFD 라, 그대로 두면 눈에는 같아
    보이는데 바이트가 달라 검색·중복 제거·정렬이 조용히 어긋난다. 브라우저는
    파일시스템에 있는 이름을 그대로 실어 보내므로 받는 쪽에서 맞춰야 한다.

    경로 구분자는 지운다. 이름을 그대로 파일 경로로 쓰지는 않지만, 나중에 저장소를
    S3 로 옮기면 그게 키의 일부가 된다.
    """
    name = unicodedata.normalize("NFC", (raw or "").strip())
    return name.replace("/", "_").replace("\\", "_")


@router.post(
    "",
    response_model=ContextResponse,
    status_code=status.HTTP_201_CREATED,
    summary="기업 컨텍스트 생성",
    responses=responses((422, "요청값 검증 실패")),
)
def create_context(body: CreateContextRequest, store: StoreDep) -> ContextResponse:
    """면접관의 기업 컨텍스트를 만든다.

    면접관 한 명에 하나라 **이미 있으면 그걸 돌려준다.** 설정 화면이 들어올 때마다
    부르게 되는 자리라, 두 번 불러서 두 개가 생기면 어느 쪽에 문서를 올렸는지가
    갈린다.
    """
    existing = store.get_context_by_interviewer(body.interviewer_id)
    if existing is not None:
        return _to_response(store, existing)

    context = Context(interviewer_id=body.interviewer_id)
    store.add_context(context)
    return _to_response(store, context)


@router.get(
    "/{contextId}",
    response_model=ContextResponse,
    summary="기업 컨텍스트 조회",
    responses=responses((404, "컨텍스트를 찾을 수 없음")),
)
def get_context(context_id: ContextIdPath, store: StoreDep) -> ContextResponse:
    return _to_response(store, _load(store, context_id))


@router.patch(
    "/{contextId}",
    response_model=ContextResponse,
    summary="기업 컨텍스트 수정",
    responses=responses((404, "컨텍스트를 찾을 수 없음"), (422, "요청값 검증 실패")),
)
def update_context(
    context_id: ContextIdPath, body: UpdateContextRequest, store: StoreDep
) -> ContextResponse:
    """넣은 항목만 바꾼다. 빈 문자열은 지우라는 뜻이라 그대로 받는다."""
    context = _load(store, context_id)
    if body.company is not None:
        context.company = body.company
    if body.team is not None:
        context.team = body.team
    if body.role is not None:
        context.role = body.role
    if body.talent_profile is not None:
        context.talent_profile = body.talent_profile
    store.save_context(context)
    return _to_response(store, context)


@router.post(
    "/{contextId}/docs",
    response_model=ContextDocResponse,
    status_code=status.HTTP_201_CREATED,
    summary="문서 업로드",
    responses=responses(
        (404, "컨텍스트를 찾을 수 없음"),
        (413, "파일이 너무 큼"),
        (415, "지원하지 않는 형식"),
    ),
)
async def upload_doc(
    context_id: ContextIdPath,
    store: StoreDep,
    file: Annotated[UploadFile, File()],
) -> ContextDocResponse:
    """면접에 쓸 문서를 올린다. `pdf` 와 `docx` 만 받는다.

    FE 도 보내기 전에 형식과 크기를 거르지만(`UploadRejection`), 그건 편의이지
    경계가 아니다. 여기서 다시 본다.
    """
    context = _load(store, context_id)
    name = _normalized_name(file.filename)
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

    doc = ContextDoc(
        context_id=context.id, name=name, kind=kind, size_bytes=len(content)
    )
    store.add_doc(doc, content)
    return ContextDocResponse(
        id=doc.id,
        name=doc.name,
        kind=doc.kind,
        size_bytes=doc.size_bytes,
        status=doc.status,
    )


@router.delete(
    "/{contextId}/docs/{docId}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="문서 삭제",
    responses=responses((404, "컨텍스트 또는 문서를 찾을 수 없음")),
)
def delete_doc(context_id: ContextIdPath, doc_id: DocIdPath, store: StoreDep) -> None:
    _load(store, context_id)
    if not store.delete_doc(context_id, doc_id):
        raise ApiError(ErrorCode.NOT_FOUND, 404, "문서를 찾을 수 없습니다.")
