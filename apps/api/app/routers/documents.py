"""documents — 관리자 전용 첨부파일 게시판 (ADR-0016, docs/11 §3.1).

게시글 = 제목 + 본문(설명용) + 첨부 1개(필수). 재업로드 = version+1 + 재인제스트(벡터는 최신만).
파일 검증: 확장자 화이트리스트·크기 상한(docs/07 §6). 중복 방어: 현재 버전 해시 충돌 시 409.
answer_cache 세대 bump = 검색 결과가 바뀌는 곳(visibility 변경·새 버전·삭제).
"""

from __future__ import annotations

import datetime
import hashlib
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from redis.asyncio import Redis
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import answer_cache
from app.code_refs import validate_category_code
from app.deps import (
    Queue,
    RequestContext,
    Storage,
    get_queue,
    get_storage,
    get_tenant_session,
    require_roles,
)
from app.schemas.documents import (
    BODY_MAX,
    DocumentDetailOut,
    DocumentListOut,
    DocumentOut,
    DocumentPatchIn,
    DocumentVersionOut,
    IndexStatus,
    Visibility,
)
from app.session import get_redis
from liviq_db.models import ContentChunk, Document, DocumentVersion, Job

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB — 초대형 업로드 차단


async def _get_owned_document(
    session: AsyncSession, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    """tenant 소유의 미삭제 문서 조회 — 없으면 404(격리 유지 위해 존재 여부 노출 안 함)."""
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없음")
    return document


async def _read_validated_file(file: UploadFile) -> tuple[bytes, str]:
    """확장자 화이트리스트·크기·빈 파일 검증 후 (bytes, suffix) 반환(fail-closed)."""
    filename = file.filename or ""
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422, detail=f"허용되지 않는 형식: {suffix or '없음'}")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 20MB를 초과")
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일")
    return data, suffix


async def _current_version_hash_exists(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    content_hash: str,
    *,
    exclude_document_id: uuid.UUID | None = None,
) -> bool:
    """미삭제 문서들의 현재 버전 중 동일 해시 존재 여부(중복 벡터·비용 방지, ADR-0016)."""
    stmt = (
        select(DocumentVersion.id)
        .join(
            Document,
            and_(
                Document.id == DocumentVersion.document_id,
                Document.tenant_id == DocumentVersion.tenant_id,
            ),
        )
        .where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
            DocumentVersion.version == Document.version,
            DocumentVersion.content_hash == content_hash,
        )
        .limit(1)
    )
    if exclude_document_id is not None:
        stmt = stmt.where(Document.id != exclude_document_id)
    return await session.scalar(stmt) is not None


@router.get("", response_model=DocumentListOut)
async def list_documents(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    index_status: Annotated[IndexStatus | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> DocumentListOut:
    stmt = select(Document).where(
        Document.tenant_id == ctx.tenant_id, Document.deleted_at.is_(None)
    )
    if index_status is not None:
        stmt = stmt.where(Document.index_status == index_status)
    if q:
        # 제목 부분일치 필터(목록 좁히기용 — 자연어 검색 아님, docs/09 §8.3 백로그).
        # ILIKE 이스케이프 생략 — %,_ 는 매치를 넓힐 뿐이고 파라미터 바인딩으로 주입 없음.
        stmt = stmt.where(Document.title.ilike(f"%{q}%"))
    rows = await session.scalars(stmt.order_by(Document.created_at.desc()))
    return DocumentListOut(
        items=[DocumentOut.model_validate(row, from_attributes=True) for row in rows]
    )


@router.post("", response_model=DocumentOut, status_code=201)
async def create_document(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    queue: Annotated[Queue, Depends(get_queue)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=200)],
    category_code_id: Annotated[uuid.UUID, Form()],
    visibility: Annotated[Visibility, Form()],
    body: Annotated[str | None, Form(max_length=BODY_MAX)] = None,
) -> DocumentOut:
    await validate_category_code(session, ctx.tenant_id, category_code_id, "DOC_CATEGORY")
    data, suffix = await _read_validated_file(file)
    content_hash = hashlib.sha256(data).hexdigest()
    if await _current_version_hash_exists(session, ctx.tenant_id, content_hash):
        raise HTTPException(status_code=409, detail="동일 파일이 이미 등록됨")

    doc_id = uuid.uuid4()
    storage_key = f"{ctx.tenant_id}/documents/{doc_id}/v1{suffix}"
    await storage.put(storage_key, data)

    document = Document(
        id=doc_id,
        tenant_id=ctx.tenant_id,
        title=title,
        category_code_id=category_code_id,
        visibility=visibility,
        body=body,
        version=1,
        index_status="pending",
        uploaded_by=ctx.user_id,
    )
    session.add(document)
    session.add(
        DocumentVersion(
            tenant_id=ctx.tenant_id,
            document_id=doc_id,
            version=1,
            filename=file.filename or f"v1{suffix}",
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(data),
            storage_key=storage_key,
            content_hash=content_hash,
            uploaded_by=ctx.user_id,
        )
    )
    session.add(
        Job(tenant_id=ctx.tenant_id, type="ingest", ref_id=doc_id, status="queued", attempts=0)
    )
    await session.flush()
    await session.refresh(document)
    await queue.enqueue("ingest_document_task", str(doc_id), str(ctx.tenant_id))
    return DocumentOut.model_validate(document, from_attributes=True)


@router.get("/{document_id}", response_model=DocumentDetailOut)
async def get_document(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    document_id: uuid.UUID,
) -> DocumentDetailOut:
    document = await _get_owned_document(session, ctx.tenant_id, document_id)
    versions = await session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.tenant_id == ctx.tenant_id,
            DocumentVersion.document_id == document_id,
        )
        .order_by(DocumentVersion.version.desc())
    )
    return DocumentDetailOut(
        id=document.id,
        title=document.title,
        category_code_id=document.category_code_id,
        visibility=document.visibility,  # type: ignore[arg-type]
        version=document.version,
        index_status=document.index_status,  # type: ignore[arg-type]
        created_at=document.created_at,
        updated_at=document.updated_at,
        body=document.body,
        versions=[DocumentVersionOut.model_validate(v, from_attributes=True) for v in versions],
    )


@router.patch("/{document_id}", response_model=DocumentOut)
async def patch_document(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    document_id: uuid.UUID,
    patch: DocumentPatchIn,
) -> DocumentOut:
    document = await _get_owned_document(session, ctx.tenant_id, document_id)
    if patch.category_code_id is not None:
        await validate_category_code(session, ctx.tenant_id, patch.category_code_id, "DOC_CATEGORY")
    if patch.title is not None:
        document.title = patch.title
    if patch.body is not None:
        document.body = patch.body
    if patch.category_code_id is not None:
        document.category_code_id = patch.category_code_id
    # visibility 변경은 검색 노출 범위를 바꾼다 → 캐시 세대 증가로 이전 답변 무효화(H4-2).
    visibility_changed = patch.visibility is not None and patch.visibility != document.visibility
    if patch.visibility is not None:
        document.visibility = patch.visibility
    await session.flush()
    if visibility_changed:
        await answer_cache.bump_generation(redis, ctx.tenant_id)
    return DocumentOut.model_validate(document, from_attributes=True)


@router.post("/{document_id}/file", response_model=DocumentOut)
async def upload_new_version(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    queue: Annotated[Queue, Depends(get_queue)],
    redis: Annotated[Redis, Depends(get_redis)],
    document_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
) -> DocumentOut:
    document = await _get_owned_document(session, ctx.tenant_id, document_id)
    data, suffix = await _read_validated_file(file)
    content_hash = hashlib.sha256(data).hexdigest()

    current_hash = await session.scalar(
        select(DocumentVersion.content_hash).where(
            DocumentVersion.tenant_id == ctx.tenant_id,
            DocumentVersion.document_id == document_id,
            DocumentVersion.version == document.version,
        )
    )
    if current_hash == content_hash:
        raise HTTPException(status_code=409, detail="현재 버전과 동일 파일")
    if await _current_version_hash_exists(
        session, ctx.tenant_id, content_hash, exclude_document_id=document_id
    ):
        raise HTTPException(status_code=409, detail="다른 문서와 동일 파일")

    new_version = document.version + 1
    storage_key = f"{ctx.tenant_id}/documents/{document_id}/v{new_version}{suffix}"
    await storage.put(storage_key, data)

    session.add(
        DocumentVersion(
            tenant_id=ctx.tenant_id,
            document_id=document_id,
            version=new_version,
            filename=file.filename or f"v{new_version}{suffix}",
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(data),
            storage_key=storage_key,
            content_hash=content_hash,
            uploaded_by=ctx.user_id,
        )
    )
    document.version = new_version
    document.index_status = "pending"
    session.add(
        Job(tenant_id=ctx.tenant_id, type="ingest", ref_id=document_id, status="queued", attempts=0)
    )
    await session.flush()
    # 새 버전은 검색 결과(최신 벡터)를 바꾼다 → 캐시 세대 증가로 이전 답변 무효화.
    await answer_cache.bump_generation(redis, ctx.tenant_id)
    await queue.enqueue("ingest_document_task", str(document_id), str(ctx.tenant_id))
    return DocumentOut.model_validate(document, from_attributes=True)


@router.get("/{document_id}/versions/{version}/download")
async def download_version(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    document_id: uuid.UUID,
    version: int,
) -> Response:
    await _get_owned_document(session, ctx.tenant_id, document_id)  # tenant 소유·미삭제 검증
    row = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.tenant_id == ctx.tenant_id,
            DocumentVersion.document_id == document_id,
            DocumentVersion.version == version,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="버전을 찾을 수 없음")
    data = await storage.get(row.storage_key)
    disposition = f"attachment; filename*=UTF-8''{quote(row.filename)}"
    return Response(
        content=data,
        media_type=row.content_type,
        headers={"Content-Disposition": disposition},
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    document_id: uuid.UUID,
) -> Response:
    document = await _get_owned_document(session, ctx.tenant_id, document_id)
    document.deleted_at = datetime.datetime.now(datetime.UTC)
    # 청크 즉시 삭제 → 검색에서 바로 사라짐(citations.chunk_id는 SET NULL로 근거 보존, §4.3).
    # 파일·버전 이력은 보존(감사 대응, ADR-0016).
    await session.execute(
        delete(ContentChunk).where(
            ContentChunk.source_type == "document",
            ContentChunk.document_id == document_id,
        )
    )
    await session.flush()
    await answer_cache.bump_generation(redis, ctx.tenant_id)
    return Response(status_code=204)


@router.post("/{document_id}/reindex", response_model=DocumentOut)
async def reindex_document(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    queue: Annotated[Queue, Depends(get_queue)],
    document_id: uuid.UUID,
) -> DocumentOut:
    document = await _get_owned_document(session, ctx.tenant_id, document_id)
    if document.index_status == "indexing":
        raise HTTPException(status_code=409, detail="색인 진행 중 — 완료 후 재색인")
    document.index_status = "pending"
    session.add(
        Job(
            tenant_id=ctx.tenant_id,
            type="ingest",
            ref_id=document.id,
            status="queued",
            attempts=0,
        )
    )
    await session.flush()
    await queue.enqueue("ingest_document_task", str(document.id), str(ctx.tenant_id))
    return DocumentOut.model_validate(document, from_attributes=True)
