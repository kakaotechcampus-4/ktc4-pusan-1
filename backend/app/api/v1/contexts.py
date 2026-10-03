"""기업 컨텍스트 — 회사·직무·인재상과 면접에 쓸 문서.

FE 가 develop 때부터 이 경로들을 부르고 있었는데 BE 에 하나도 없어서 목으로만
돌고 있었다 (`frontend/src/api/context.ts`, `contextSettings.ts`).

**면접이 아니라 면접관에게 딸린다.** 회사 정보와 JD 는 면접마다 바뀌지 않으므로
설정에 한 번 넣고 계속 쓴다는 것이 #79 의 제안이고, 그래서 면접관 한 명에 하나다.
주인은 토큰의 사용자이고, 남의 컨텍스트는 없는 것과 같이 404 다 (#130).

문서 본문 추출(파싱)은 이 범위가 아니다. 누가 하는지가 안 정해졌고(#70 의
「`resume` 가 합의안은 본문 문자열인데 현재는 스토리지 키」), 지금은 올라온 즉시
`ready` 다. `parsing` 상태는 FE 가 이미 갖고 있어 나중에 붙이면 된다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, UploadFile, status

from app.api.deps import (
    CurrentUserDep,
    OwnedContextDep,
    StoreDep,
    get_owned_context,
)
from app.core.errors import LOGIN_REQUIRED, ApiError, ErrorCode, responses
from app.core.uploads import read_upload
from app.domain.models import Context, ContextDoc
from app.domain.store import Store
from app.schemas import (
    ContextDocResponse,
    ContextResponse,
    UpdateContextRequest,
)

router = APIRouter(prefix="/contexts", tags=["기업 컨텍스트"])

ContextIdPath = Annotated[str, Path(alias="contextId")]
DocIdPath = Annotated[str, Path(alias="docId")]

_NOT_FOUND = (404, "컨텍스트를 찾을 수 없음 (남의 컨텍스트 포함)")


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


@router.get(
    "/current",
    response_model=ContextResponse,
    summary="기업 컨텍스트 조회 (현재 조직)",
    responses=responses(LOGIN_REQUIRED),
)
def get_current_context(user: CurrentUserDep, store: StoreDep) -> ContextResponse:
    """지금 쓰는 기업 컨텍스트를 돌려준다. 없으면 만들어서 돌려준다.

    FE 가 설정 화면에 들어올 때 `contextId` 를 모르는 상태다. 그래서 id 없이 부를 수
    있는 자리가 하나 필요하다 — FE 도 「조직 컨텍스트를 알려주는 API 가 없어
    contextId 를 상수로 둔다」고 적어 두고 `'ctx_demo'` 를 쓰고 있다.

    **주인은 로그인한 사용자다.** 조직이 아직 없어서 면접관 한 명에 하나다.

    없으면 만드는 이유는 「설정을 아직 안 만들었다」와 「설정이 비어 있다」를 FE 가
    구분할 필요가 없어서다. 빈 컨텍스트를 받으면 그냥 채우면 된다.
    """
    context = store.ensure_context(Context(owner_id=user.id))
    return _to_response(store, context)


@router.get(
    "/{contextId}",
    response_model=ContextResponse,
    summary="기업 컨텍스트 조회",
    responses=responses(LOGIN_REQUIRED, _NOT_FOUND),
)
def get_context(context: OwnedContextDep, store: StoreDep) -> ContextResponse:
    return _to_response(store, context)


@router.patch(
    "/{contextId}",
    response_model=ContextResponse,
    summary="기업 컨텍스트 수정",
    responses=responses(LOGIN_REQUIRED, _NOT_FOUND, (422, "요청값 검증 실패")),
)
def update_context(
    body: UpdateContextRequest, context: OwnedContextDep, store: StoreDep
) -> ContextResponse:
    """넣은 항목만 바꾼다. 빈 문자열은 지우라는 뜻이라 그대로 받는다."""
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
        LOGIN_REQUIRED,
        _NOT_FOUND,
        (413, "파일이 너무 큼"),
        (415, "지원하지 않는 형식"),
    ),
)
async def upload_doc(
    context: OwnedContextDep,
    store: StoreDep,
    file: Annotated[UploadFile, File()],
) -> ContextDocResponse:
    """면접에 쓸 문서를 올린다. `pdf` 와 `docx` 만 받는다.

    FE 도 보내기 전에 형식과 크기를 거르지만(`UploadRejection`), 그건 편의이지
    경계가 아니다. 여기서 다시 본다.
    """
    name, kind, content = await read_upload(file)

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
    responses=responses(
        LOGIN_REQUIRED, (404, "컨텍스트 또는 문서를 찾을 수 없음 (남의 것 포함)")
    ),
    # 주인 검사를 인자가 아니라 여기 둔다. 인자로 받으면 경로 파라미터가 명세와
    # 반대 순서(docId → contextId)로 문서화된다.
    dependencies=[Depends(get_owned_context)],
)
def delete_doc(context_id: ContextIdPath, doc_id: DocIdPath, store: StoreDep) -> None:
    if not store.delete_doc(context_id, doc_id):
        raise ApiError(ErrorCode.NOT_FOUND, 404, "문서를 찾을 수 없습니다.")
