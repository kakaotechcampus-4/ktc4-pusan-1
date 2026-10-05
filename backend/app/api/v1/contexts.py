"""기업 컨텍스트 — 회사·직무·인재상과 면접에 쓸 문서.

FE 가 develop 때부터 이 경로들을 부르고 있었는데 BE 에 하나도 없어서 목으로만
돌고 있었다 (`frontend/src/api/context.ts`, `contextSettings.ts`).

**면접이 아니라 면접관에게 딸린다.** 회사 정보와 JD 는 면접마다 바뀌지 않으므로
설정에 한 번 넣고 계속 쓴다는 것이 #79 의 제안이고, 그래서 면접관 한 명에 하나다.
주인은 토큰의 사용자이고, 남의 컨텍스트는 없는 것과 같이 404 다 (#130).

문서는 PDF 만 받고, 올라오면 응답 뒤에 Helpy Document Vision 으로 본문을 뽑는다
(#143, `app/services/documents.py`). 그 본문을 읽는 것은 AI Agent 다 (#70).
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Path,
    UploadFile,
    status,
)
from starlette.concurrency import run_in_threadpool

from app.api.deps import (
    CurrentUserDep,
    OwnedContextDep,
    ParserDep,
    StoreDep,
    get_owned_context,
)
from app.core.config import settings
from app.core.errors import LOGIN_REQUIRED, ApiError, ErrorCode, responses
from app.core.uploads import read_upload
from app.domain.models import Context, ContextDoc, DocCategory
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


def _doc_response(doc: ContextDoc) -> ContextDocResponse:
    return ContextDocResponse(
        id=doc.id,
        name=doc.name,
        kind=doc.kind,
        size_bytes=doc.size_bytes,
        status=doc.shown_status(settings.doc_parse_timeout),
        category=doc.category,
    )


def _to_response(store: Store, context: Context) -> ContextResponse:
    return ContextResponse(
        id=context.id,
        company=context.company,
        team=context.team,
        role=context.role,
        talent_profile=context.talent_profile,
        docs=[_doc_response(doc) for doc in store.list_docs(context.id)],
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
    parser: ParserDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    category: Annotated[DocCategory, Form()] = DocCategory.INTERNAL,
) -> ContextDocResponse:
    """면접에 쓸 문서를 올린다. **PDF 만 받는다.**

    FE 도 보내기 전에 형식과 크기를 거르지만(`UploadRejection`), 그건 편의이지
    경계가 아니다. 여기서 다시 본다.

    **응답은 `parsing` 으로 바로 나간다.** 본문 추출(Helpy Document Vision)은 평균
    10초가 걸려서 응답 뒤에 따로 돈다. FE 는 `parsing` 인 문서가 있는 동안
    컨텍스트를 다시 조회하면 `ready` 나 `failed` 로 바뀐 것을 본다.
    """
    name, kind, content = await read_upload(file)

    doc = ContextDoc(
        context_id=context.id,
        name=name,
        kind=kind,
        size_bytes=len(content),
        category=category,
    )
    # 저장소는 동기다. async 라우트가 그대로 부르면 그동안 이벤트 루프가 멈춘다.
    # 50MB 까지 받으므로 수 초다 (#133). 추출(`finish_doc`)은 BackgroundTasks 가
    # 스레드풀에서 돌린다.
    await run_in_threadpool(store.add_doc, doc, content)
    background.add_task(
        lambda: store.finish_doc(
            doc.context_id, doc.id, parser.extract_text(doc.name, content)
        )
    )
    return _doc_response(doc)


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
