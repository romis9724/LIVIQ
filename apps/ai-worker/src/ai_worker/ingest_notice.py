"""공지 인제스트 — published 공지 본문 + 파싱 가능 첨부 → content_chunks(source_type=notice).

발행 시점·published 수정·첨부 변경마다 재인제스트된다(H8-3, ADR-0015 개정 노트). 잡이 늦게
돌 때를 대비해 **published·미삭제가 아니면 스킵**한다(인제스트 published-only는 검색 조인
검증과 함께 미발행 공지 미노출의 이중 방어). 재인제스트는 멱등 — 기존 notice 청크 전체 삭제
후 재삽입(chunk_index 연속). 마스킹 미적용: 공지는 전 입주민 공개 문서라 임베딩이 추가 노출을
만들지 않는다(documents 인제스트 선례, ADR-0015).

세션은 호출자(arq 태스크·cron)가 tenant 컨텍스트(`app.tenant_id`)를 설정한 것을 받는다 —
worker role은 BYPASSRLS 없이 RLS를 그대로 받는다(docs/03 §5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from ai_core.rag import chunk_text
from ai_worker.ingest import Downloader, embed_chunks
from ai_worker.parsing import SUPPORTED_SUFFIXES, extract_text
from liviq_db.models import ContentChunk, Notice, NoticeAttachment


@dataclass(frozen=True)
class NoticeIngestResult:
    notice_id: uuid.UUID
    chunk_count: int
    status: str  # indexed | skipped


async def ingest_notice(
    session: AsyncSession,
    *,
    llm: LlmClient,
    download: Downloader,
    notice_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> NoticeIngestResult:
    """공지 1건 인제스트. published·미삭제가 아니면 청크 생성 없이 스킵(늦은 잡 방어)."""
    notice = await session.scalar(
        select(Notice).where(
            Notice.id == notice_id,
            Notice.tenant_id == tenant_id,
            Notice.status == "published",
            Notice.deleted_at.is_(None),
        )
    )
    if notice is None:
        return NoticeIngestResult(notice_id, 0, "skipped")

    parts = [f"{notice.title}\n\n{notice.body}"]
    attachments = await session.scalars(
        select(NoticeAttachment)
        .where(
            NoticeAttachment.notice_id == notice_id,
            NoticeAttachment.tenant_id == tenant_id,
        )
        .order_by(NoticeAttachment.created_at.asc())
    )
    for att in attachments:
        # 첨부 storage_key엔 확장자가 없다(§4.4 키 포맷) → filename으로 형식 판별.
        if PurePosixPath(att.filename).suffix.lower() not in SUPPORTED_SUFFIXES:
            continue  # hwp·docx·xlsx·이미지는 벡터화 대상 아님(첨부 화이트리스트 축소 아님)
        raw = await download(att.storage_key)
        parts.append(extract_text(att.filename, raw))

    text = "\n\n".join(p for p in parts if p.strip())
    chunks = chunk_text(text)

    # 멱등 재색인: 기존 notice 청크 삭제 → 재삽입(chunk_index 연속).
    await session.execute(
        delete(ContentChunk).where(
            ContentChunk.source_type == "notice",
            ContentChunk.notice_id == notice_id,
        )
    )
    if not chunks:
        return NoticeIngestResult(notice_id, 0, "indexed")

    vectors = await embed_chunks(llm, chunks)
    session.add_all(
        ContentChunk(
            tenant_id=tenant_id,
            source_type="notice",
            document_id=None,
            notice_id=notice_id,
            chunk_index=chunk.index,
            content=chunk.content,
            heading=chunk.heading,
            token_count=chunk.token_count,
            embedding=vector,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    )
    await session.flush()  # 청크를 즉시 확정(검색 raw SQL은 autoflush에 의존하지 않음)
    return NoticeIngestResult(notice_id, len(chunks), "indexed")
