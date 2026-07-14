"""인제스트 통합 테스트 — 실 PG + 가짜 LLM/다운로더."""

from __future__ import annotations

import uuid

from conftest import RULES_TEXT
from conftest import seed_document as _seed_document
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from ai_worker.ingest import ingest_document
from liviq_db.models import Document, DocumentChunk


def _downloader(data: bytes) -> object:
    async def download(storage_key: str) -> bytes:
        return data

    return download


async def test_ingest_creates_chunks_and_marks_indexed(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    tenant_id, doc_id = await _seed_document(session, storage_key="t/rules.txt")
    result = await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(RULES_TEXT.encode()),  # type: ignore[arg-type]
        document_id=doc_id,
        tenant_id=tenant_id,
    )
    assert result.status == "indexed"
    assert result.chunk_count == 2  # 제1조·제2조 섹션

    status = await session.scalar(select(Document.index_status).where(Document.id == doc_id))
    assert status == "indexed"
    count = await session.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    )
    assert count == 2


async def test_reingest_is_idempotent(session: AsyncSession, fake_llm: LlmClient) -> None:
    tenant_id, doc_id = await _seed_document(session, storage_key="t/rules.txt")
    for _ in range(2):
        result = await ingest_document(
            session,
            llm=fake_llm,
            download=_downloader(RULES_TEXT.encode()),  # type: ignore[arg-type]
            document_id=doc_id,
            tenant_id=tenant_id,
        )
        assert result.status == "indexed"
    count = await session.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    )
    assert count == 2  # 재색인해도 중복 없음


async def test_unsupported_format_marks_failed(session: AsyncSession, fake_llm: LlmClient) -> None:
    tenant_id, doc_id = await _seed_document(session, storage_key="t/roster.hwp")
    result = await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(b"..."),  # type: ignore[arg-type]
        document_id=doc_id,
        tenant_id=tenant_id,
    )
    assert result.status == "failed"
    status = await session.scalar(select(Document.index_status).where(Document.id == doc_id))
    assert status == "failed"


async def test_missing_document_fails_cleanly(session: AsyncSession, fake_llm: LlmClient) -> None:
    result = await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(b""),  # type: ignore[arg-type]
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )
    assert result.status == "failed"
    assert result.error == "문서 없음"
