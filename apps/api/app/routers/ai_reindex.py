"""ai_reindex — 전 단지 재색인 트리거·진행 조회 (SYS_ADMIN 전용, H15-3, docs/03 §4.7).

임베딩 백엔드·`chunk_max_tokens`는 **위험 노브**다 — 바꾸면 기존 벡터와 불일치가 남는다.
반영은 이 트리거로 완성한다: 삭제 안 된 전 단지 문서(최신 버전)와 발행 공지를 인제스트 큐에
다시 넣는다(실행은 ai-worker — 잡마다 활성 설정을 읽는다).

단지 콘텐츠를 **읽지 않는다** — id만 모아 enqueue한다(SYS_ADMIN 비열람 원칙 유지, docs/06 §2).
RLS는 단지별 `app.tenant_id` 전환으로 정상 경로를 그대로 받는다(admin_tenants와 같은 패턴).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SYSTEM_TENANT_ID
from app.deps import Queue, RequestContext, get_queue, get_tenant_session, require_roles
from app.schemas.ai_config import ReindexOut, ReindexStatusOut
from liviq_db.models import Document, Notice, Tenant

router = APIRouter(prefix="/system/ai-config", tags=["ai-config"])

_SYS_ADMIN = require_roles("SYS_ADMIN")

# 재색인 대기 상태 — 업로드 직후와 같은 어휘(documents.index_status)
PENDING_STATUS = "pending"


async def _tenant_ids(session: AsyncSession) -> list[uuid.UUID]:
    """시스템 테넌트를 뺀 전 단지 id(tenants는 RLS 예외)."""
    return list(
        await session.scalars(
            select(Tenant.id).where(Tenant.id != SYSTEM_TENANT_ID).order_by(Tenant.created_at)
        )
    )


async def _set_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """RLS 컨텍스트를 해당 단지로 전환(트랜잭션 로컬)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )


@router.post("/reindex", response_model=ReindexOut)
async def trigger_reindex(
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> ReindexOut:
    """전 단지 문서·발행 공지 재인제스트 enqueue. 문서는 index_status를 pending으로 리셋."""
    documents = 0
    notices = 0
    for tenant_id in await _tenant_ids(session):
        await _set_tenant(session, tenant_id)
        doc_ids = list(
            await session.scalars(
                select(Document.id).where(
                    Document.tenant_id == tenant_id, Document.deleted_at.is_(None)
                )
            )
        )
        if doc_ids:
            # 진행 표시가 먼저 pending으로 돌아야 관리자가 재색인 중임을 안다.
            await session.execute(
                update(Document)
                .where(Document.tenant_id == tenant_id, Document.id.in_(doc_ids))
                .values(index_status=PENDING_STATUS)
            )
        notice_ids = list(
            await session.scalars(
                select(Notice.id).where(
                    Notice.tenant_id == tenant_id,
                    Notice.status == "published",  # 벡터화 대상은 발행 공지만(H8-3)
                    Notice.deleted_at.is_(None),
                )
            )
        )
        for doc_id in doc_ids:
            await queue.enqueue("ingest_document_task", str(doc_id), str(tenant_id))
        for notice_id in notice_ids:
            await queue.enqueue("ingest_notice_task", str(notice_id), str(tenant_id))
        documents += len(doc_ids)
        notices += len(notice_ids)
    return ReindexOut(enqueued_documents=documents, enqueued_notices=notices)


@router.get("/reindex-status", response_model=ReindexStatusOut)
async def get_reindex_status(
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> ReindexStatusOut:
    """전 단지 문서 색인 상태 집계(공지는 상태 컬럼이 없어 대상 아님)."""
    counts: dict[str, int] = {}
    for tenant_id in await _tenant_ids(session):
        await _set_tenant(session, tenant_id)
        rows = await session.execute(
            select(Document.index_status, func.count())
            .where(Document.tenant_id == tenant_id, Document.deleted_at.is_(None))
            .group_by(Document.index_status)
        )
        for status, count in rows:
            counts[status] = counts.get(status, 0) + count
    return ReindexStatusOut(
        pending=counts.get(PENDING_STATUS, 0),
        indexing=counts.get("indexing", 0),
        indexed=counts.get("indexed", 0),
        failed=counts.get("failed", 0),
        total=sum(counts.values()),
    )
