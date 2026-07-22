"""문서 인제스트 — 원본 → 파싱 → 청킹 → 임베딩 → pgvector (docs/01 §5.1, 11 §3.1).

의존성(다운로드·LLM·세션)은 주입받아 단위 테스트 가능하게 유지한다.
세션은 호출자(arq 태스크)가 tenant 컨텍스트(`app.tenant_id`)를 설정한 것을 받는다 —
worker role은 BYPASSRLS 없이 RLS를 그대로 받는다(docs/03 §5).
재색인은 멱등: 기존 청크 전체 삭제 후 재삽입(citations.chunk_id는 SET NULL로 보존).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from ai_core.rag import chunk_text
from ai_worker.parsing import UnsupportedFormatError, extract_text
from liviq_db.models import ContentChunk, Document, DocumentVersion

# 임베딩 호출 배치 크기(페이로드 상한·재시도 단위 균형)
EMBED_BATCH_SIZE = 32

Downloader = Callable[[str], Awaitable[bytes]]


@dataclass(frozen=True)
class IngestResult:
    document_id: uuid.UUID
    chunk_count: int
    status: str  # indexed | failed
    error: str | None = None


async def ingest_document(
    session: AsyncSession,
    *,
    llm: LlmClient,
    download: Downloader,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> IngestResult:
    """문서 1건 인제스트. 실패 시 index_status=failed 기록 후 결과 반환(예외 삼킴 금지 —
    복구 불가 사유는 IngestResult.error로 노출, 인프라 오류는 그대로 전파해 arq 재시도)."""
    document = await session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if document is None:
        return IngestResult(document_id, 0, "failed", error="문서 없음")

    # 벡터는 항상 최신 버전만(ADR-0016) — documents.version과 일치하는 첨부를 색인한다.
    version = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.version == document.version,
        )
    )
    if version is None:
        await _mark_failed(session, document_id)
        return IngestResult(document_id, 0, "failed", error="버전 없음")

    await session.execute(
        update(Document).where(Document.id == document_id).values(index_status="indexing")
    )

    try:
        raw = await download(version.storage_key)
        text = extract_text(version.storage_key, raw)
        chunks = chunk_text(text)
    except UnsupportedFormatError as exc:
        await _mark_failed(session, document_id)
        return IngestResult(document_id, 0, "failed", error=str(exc))

    if not chunks:
        await _mark_failed(session, document_id)
        return IngestResult(document_id, 0, "failed", error="추출된 텍스트 없음")

    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        vectors.extend(await llm.embed([c.content for c in batch]))

    # 멱등 재색인: 기존 청크 삭제 → 재삽입
    await session.execute(
        delete(ContentChunk).where(
            ContentChunk.source_type == "document",
            ContentChunk.document_id == document_id,
        )
    )
    session.add_all(
        ContentChunk(
            tenant_id=tenant_id,
            source_type="document",
            document_id=document_id,
            notice_id=None,
            chunk_index=chunk.index,
            content=chunk.content,
            heading=chunk.heading,
            token_count=chunk.token_count,
            embedding=vector,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    )
    await session.execute(
        update(Document).where(Document.id == document_id).values(index_status="indexed")
    )
    return IngestResult(document_id, len(chunks), "indexed")


async def _mark_failed(session: AsyncSession, document_id: uuid.UUID) -> None:
    await session.execute(
        update(Document).where(Document.id == document_id).values(index_status="failed")
    )
