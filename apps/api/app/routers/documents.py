"""documents — 업로드(S3)→행 생성→인제스트 큐잉, 목록/상태 (docs/11 §3.1).

파일 검증: 확장자 화이트리스트·크기 상한(docs/07 §6 업로드 방어).
멱등: content_hash 중복이면 기존 문서 반환(재임베딩 없음, docs/08 §6).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import answer_cache
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
    DocumentListOut,
    DocumentOut,
    DocumentPatchIn,
    DocumentUploadOut,
    IndexStatus,
    SourceType,
    Visibility,
)
from app.session import get_redis
from liviq_db.models import Document, Job

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


@router.post("", response_model=DocumentUploadOut, status_code=201)
async def upload_document(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    queue: Annotated[Queue, Depends(get_queue)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=200)],
    source_type: Annotated[SourceType, Form()],
    visibility: Annotated[Visibility, Form()],
) -> DocumentUploadOut:
    filename = file.filename or ""
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422, detail=f"허용되지 않는 형식: {suffix or '없음'}")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 20MB를 초과")
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일")

    content_hash = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(Document).where(
            Document.tenant_id == ctx.tenant_id,
            Document.content_hash == content_hash,
            Document.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return DocumentUploadOut(
            id=existing.id,
            index_status=cast(IndexStatus, existing.index_status),
            duplicate=True,
        )

    doc_id = uuid.uuid4()
    storage_key = f"{ctx.tenant_id}/documents/{doc_id}{suffix}"
    await storage.put(storage_key, data)

    document = Document(
        id=doc_id,
        tenant_id=ctx.tenant_id,
        title=title,
        source_type=source_type,
        visibility=visibility,
        storage_key=storage_key,
        content_hash=content_hash,
        index_status="pending",
        uploaded_by=ctx.user_id,
    )
    session.add(document)
    session.add(
        Job(tenant_id=ctx.tenant_id, type="ingest", ref_id=doc_id, status="queued", attempts=0)
    )
    await session.flush()
    await queue.enqueue("ingest_document_task", str(doc_id), str(ctx.tenant_id))
    return DocumentUploadOut(id=doc_id, index_status="pending")


@router.patch("/{document_id}", response_model=DocumentOut)
async def patch_document(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    document_id: uuid.UUID,
    body: DocumentPatchIn,
) -> DocumentOut:
    document = await _get_owned_document(session, ctx.tenant_id, document_id)
    if body.title is not None:
        document.title = body.title
    # visibility 변경은 검색 노출 범위를 바꾼다 → 캐시 세대 증가로 이전 답변 무효화(H4-2).
    visibility_changed = body.visibility is not None and body.visibility != document.visibility
    if body.visibility is not None:
        document.visibility = body.visibility
    await session.flush()
    if visibility_changed:
        await answer_cache.bump_generation(redis, ctx.tenant_id)
    return DocumentOut.model_validate(document, from_attributes=True)


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
