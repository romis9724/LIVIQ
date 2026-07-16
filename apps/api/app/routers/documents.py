"""documents — 업로드(S3)→행 생성→인제스트 큐잉, 목록/상태 (docs/11 §3.1).

파일 검증: 확장자 화이트리스트·크기 상한(docs/07 §6 업로드 방어).
멱등: content_hash 중복이면 기존 문서 반환(재임베딩 없음, docs/08 §6).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    DocumentUploadOut,
    IndexStatus,
    SourceType,
    Visibility,
)
from liviq_db.models import Document, Job

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB — 초대형 업로드 차단


@router.get("", response_model=DocumentListOut)
async def list_documents(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER", "STAFF"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> DocumentListOut:
    rows = await session.scalars(
        select(Document)
        .where(Document.tenant_id == ctx.tenant_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
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
