"""공지 인제스트 통합 — 실 PG + 가짜 LLM/다운로더 (H8-3).

published 공지 본문+파싱 가능 첨부 → content_chunks(source_type=notice). .hwp 등 비파싱 첨부
스킵·재인제스트 멱등·미발행/삭제 공지 스킵을 본다. CRITICAL(미노출)의 인제스트 published-only 층.
"""

from __future__ import annotations

import io
import uuid

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from ai_worker.ingest_notice import ingest_notice
from liviq_db.models import ContentChunk, Notice, NoticeAttachment, Tenant

BODY = "제1조 목적\n관리 안내의 목적을 정한다."
MD_MARKER = "첨부고유표식제2조"
HWP_MARKER = "명부비밀표식"


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _downloader(objects: dict[str, bytes], seen: list[str]):
    async def download(storage_key: str) -> bytes:
        seen.append(storage_key)
        return objects[storage_key]

    return download


async def _seed_notice(
    session: AsyncSession,
    *,
    status: str = "published",
    deleted: bool = False,
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> tuple[uuid.UUID, uuid.UUID, dict[str, bytes]]:
    """tenant + 공지(+첨부) 시드. attachments=(filename, storage_key, bytes) 목록.

    (tenant_id, notice_id, storage_key→bytes 맵) 반환.
    """
    import datetime

    tenant = Tenant(name="t", status="active")
    session.add(tenant)
    await session.flush()
    notice = Notice(
        tenant_id=tenant.id,
        title="단수 안내",
        body=BODY,
        status=status,
        pinned=False,
        audience="ALL",
        published_at=datetime.datetime.now(datetime.UTC) if status == "published" else None,
        deleted_at=datetime.datetime.now(datetime.UTC) if deleted else None,
    )
    session.add(notice)
    await session.flush()
    objects: dict[str, bytes] = {}
    for filename, storage_key, data in attachments or []:
        session.add(
            NoticeAttachment(
                tenant_id=tenant.id,
                notice_id=notice.id,
                filename=filename,
                content_type="application/octet-stream",
                size_bytes=len(data),
                storage_key=storage_key,
            )
        )
        objects[storage_key] = data
    await session.flush()
    return tenant.id, notice.id, objects


async def test_ingest_body_and_parsable_attachments(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    tenant_id, notice_id, objects = await _seed_notice(
        session,
        attachments=[
            (
                "안내.md",
                "t/notices/n/md",
                f"# 안내\n{MD_MARKER} 지하주차장은 24시간 개방한다.".encode(),
            ),
            ("명부.hwp", "t/notices/n/hwp", HWP_MARKER.encode()),  # 비파싱 → 스킵
            ("문서.pdf", "t/notices/n/pdf", _blank_pdf()),  # 파싱 대상(빈 텍스트)
        ],
    )
    seen: list[str] = []
    result = await ingest_notice(
        session,
        llm=fake_llm,
        download=_downloader(objects, seen),  # type: ignore[arg-type]
        notice_id=notice_id,
        tenant_id=tenant_id,
    )
    assert result.status == "indexed"
    assert result.chunk_count >= 1

    chunks = list(
        await session.scalars(select(ContentChunk).where(ContentChunk.notice_id == notice_id))
    )
    joined = "\n".join(c.content for c in chunks)
    assert all(c.source_type == "notice" and c.document_id is None for c in chunks)
    assert MD_MARKER in joined  # 파싱 가능 첨부 본문 반영
    assert HWP_MARKER not in joined  # .hwp는 벡터화 대상 아님
    # .hwp는 다운로드조차 하지 않는다(확장자 선필터). .pdf는 파싱 시도.
    assert "t/notices/n/hwp" not in seen
    assert "t/notices/n/pdf" in seen and "t/notices/n/md" in seen


async def test_reingest_is_idempotent(session: AsyncSession, fake_llm: LlmClient) -> None:
    tenant_id, notice_id, objects = await _seed_notice(
        session, attachments=[("안내.md", "t/notices/n/md", b"# a\n" + MD_MARKER.encode())]
    )
    for _ in range(2):
        result = await ingest_notice(
            session,
            llm=fake_llm,
            download=_downloader(objects, []),  # type: ignore[arg-type]
            notice_id=notice_id,
            tenant_id=tenant_id,
        )
        assert result.status == "indexed"
    count = await session.scalar(
        select(func.count()).select_from(ContentChunk).where(ContentChunk.notice_id == notice_id)
    )
    assert count == result.chunk_count  # 재색인해도 중복 없음


@pytest.mark.parametrize(
    ("status", "deleted"),
    [("draft", False), ("scheduled", False), ("published", True)],
)
async def test_unpublished_or_deleted_is_skipped(
    session: AsyncSession, fake_llm: LlmClient, status: str, deleted: bool
) -> None:
    tenant_id, notice_id, objects = await _seed_notice(session, status=status, deleted=deleted)
    result = await ingest_notice(
        session,
        llm=fake_llm,
        download=_downloader(objects, []),  # type: ignore[arg-type]
        notice_id=notice_id,
        tenant_id=tenant_id,
    )
    assert result.status == "skipped"
    count = await session.scalar(
        select(func.count()).select_from(ContentChunk).where(ContentChunk.notice_id == notice_id)
    )
    assert count == 0  # 미발행/삭제 공지는 청크 미생성(검색 미노출)
