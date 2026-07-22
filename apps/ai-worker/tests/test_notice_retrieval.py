"""공지 벡터 검색 노출 — PgVectorRetriever가 published 공지 청크만 반환 (H8-3, CRITICAL).

실 PG에서 검색 SQL의 notice 조인(published·미삭제)이 미발행 공지 청크를 배제하는지 본다.
draft 공지에 청크를 강제로 심어도 조인 검증으로 걸러져야 한다(인제스트 published-only와 이중 방어).
"""

from __future__ import annotations

import datetime
import uuid

from conftest import RULES_TEXT
from conftest import seed_document as _seed_document
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from ai_core.rag.retrieval import PgVectorRetriever
from ai_worker.ingest import Downloader, ingest_document
from ai_worker.ingest_notice import ingest_notice
from liviq_db.models import ContentChunk, Notice, Tenant

_QUERY = "주차 안내"


def _downloader(data: bytes) -> Downloader:
    async def download(storage_key: str) -> bytes:
        return data

    return download


async def _seed_notice(session: AsyncSession, tenant_id: uuid.UUID, *, status: str) -> uuid.UUID:
    now = datetime.datetime.now(datetime.UTC)
    notice = Notice(
        tenant_id=tenant_id,
        title=f"{status} 공지",
        body="지하주차장은 24시간 개방한다.",
        status=status,
        pinned=False,
        audience="ALL",
        published_at=now if status == "published" else None,
        scheduled_at=now if status == "scheduled" else None,
    )
    session.add(notice)
    await session.flush()
    return notice.id


async def _force_chunk(session: AsyncSession, tenant_id: uuid.UUID, notice_id: uuid.UUID) -> None:
    """미발행 공지에 청크를 강제로 심는다(조인 배제가 유일한 방어선임을 검증)."""
    session.add(
        ContentChunk(
            tenant_id=tenant_id,
            source_type="notice",
            notice_id=notice_id,
            chunk_index=0,
            content="강제 삽입 청크",
            embedding=[0.01] * 1024,
        )
    )
    await session.flush()


async def _search(session: AsyncSession, llm: LlmClient, tenant_id: uuid.UUID) -> list:
    query_vec = (await llm.embed([_QUERY]))[0]
    retriever = PgVectorRetriever(session)
    return await retriever.search(
        query_vec, tenant_id=tenant_id, visibilities=["ALL", "RESIDENT", "ADMIN", "COUNCIL"]
    )


async def test_published_notice_chunks_are_searchable(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    tenant = Tenant(name="t", status="active")
    session.add(tenant)
    await session.flush()
    notice_id = await _seed_notice(session, tenant.id, status="published")
    await ingest_notice(
        session, llm=fake_llm, download=_downloader(b""), notice_id=notice_id, tenant_id=tenant.id
    )

    results = await _search(session, fake_llm, tenant.id)
    notice_hits = [r for r in results if r.document_id is None]
    assert notice_hits, "published 공지 청크가 검색에 노출되지 않음"
    assert notice_hits[0].document_title == "published 공지"  # title=공지 제목


async def test_draft_and_deleted_notice_chunks_excluded(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    tenant = Tenant(name="t", status="active")
    session.add(tenant)
    await session.flush()
    draft_id = await _seed_notice(session, tenant.id, status="draft")
    scheduled_id = await _seed_notice(session, tenant.id, status="scheduled")
    await _force_chunk(session, tenant.id, draft_id)
    await _force_chunk(session, tenant.id, scheduled_id)

    results = await _search(session, fake_llm, tenant.id)
    assert results == [], "미발행 공지 청크가 검색에 노출됨(CRITICAL 위반)"


async def test_document_search_regression(session: AsyncSession, fake_llm: LlmClient) -> None:
    """document 청크 검색은 다형 SQL 전환 후에도 회귀 없이 동작한다."""
    tenant_id, doc_id = await _seed_document(session, storage_key="t/rules.txt")
    await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(RULES_TEXT.encode()),
        document_id=doc_id,
        tenant_id=tenant_id,
    )
    results = await _search(session, fake_llm, tenant_id)
    doc_hits = [r for r in results if r.document_id == doc_id]
    assert doc_hits, "document 청크 검색이 회귀됨"
    assert doc_hits[0].document_title == "관리규약"
