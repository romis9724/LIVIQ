"""인제스트 통합 테스트 — 실 PG + 가짜 LLM/다운로더."""

from __future__ import annotations

import uuid

import pytest
from conftest import RULES_TEXT
from conftest import seed_document as _seed_document
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from ai_core.masking import MaskingFailedError
from ai_worker.ingest import ingest_document
from liviq_db.models import ContentChunk, Document

PII_TEXT = "제1조 연락\n관리사무소 담당자 연락처는 010-1234-5678, 이메일은 kim@example.com 이다."


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
        select(func.count()).select_from(ContentChunk).where(ContentChunk.document_id == doc_id)
    )
    assert count == 2


async def test_clause_is_persisted_for_article_chunks(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    """조항 청크는 clause 컬럼에 조항 번호가 남아야 한다.

    이 배선이 없으면 prompt.build_context_block이 인용 출처 줄에 조항을 표시하지 못한다
    (H15-2 #3에서 clause가 한 번도 기록되지 않아 항상 NULL이었다).
    """
    tenant_id, doc_id = await _seed_document(session, storage_key="t/clause.txt")
    await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(RULES_TEXT.encode()),  # type: ignore[arg-type]
        document_id=doc_id,
        tenant_id=tenant_id,
    )
    rows = (
        (
            await session.execute(
                select(ContentChunk.clause)
                .where(ContentChunk.document_id == doc_id)
                .order_by(ContentChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    assert list(rows) == ["제1조 목적", "제2조 주차"]


async def test_embedding_payload_is_masked(
    session: AsyncSession, fake_llm: LlmClient, embed_payloads: list[str]
) -> None:
    """임베딩 페이로드엔 원문 PII 없음(플레이스홀더만) — DB 청크는 원문 유지(규칙 2, docs/06)."""
    tenant_id, doc_id = await _seed_document(session, storage_key="t/contact.txt")
    result = await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(PII_TEXT.encode()),  # type: ignore[arg-type]
        document_id=doc_id,
        tenant_id=tenant_id,
    )
    assert result.status == "indexed"

    sent = "\n".join(embed_payloads)
    assert sent, "임베딩 호출이 없었다면 검증 자체가 무의미"
    assert "010-1234-5678" not in sent
    assert "kim@example.com" not in sent
    assert "<PII:PHONE:" in sent and "<PII:EMAIL:" in sent

    stored = await session.scalars(
        select(ContentChunk.content).where(ContentChunk.document_id == doc_id)
    )
    assert "010-1234-5678" in "\n".join(stored)  # 원문은 DB에 그대로(RLS 보호 대상)


async def test_masking_failure_marks_failed_without_embedding(
    session: AsyncSession,
    fake_llm: LlmClient,
    embed_payloads: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """마스킹 실패 시 임베딩 호출 없이 failed — fail-closed(규칙 2)."""

    def _boom(text: str, **kwargs: object) -> object:
        raise MaskingFailedError("마스킹 후 PII 잔존")

    monkeypatch.setattr("ai_worker.ingest.ensure_masked", _boom)
    tenant_id, doc_id = await _seed_document(session, storage_key="t/rules.txt")
    result = await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(RULES_TEXT.encode()),  # type: ignore[arg-type]
        document_id=doc_id,
        tenant_id=tenant_id,
    )
    assert result.status == "failed"
    assert embed_payloads == []  # 마스킹 전에 막혔다
    status = await session.scalar(select(Document.index_status).where(Document.id == doc_id))
    assert status == "failed"


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
        select(func.count()).select_from(ContentChunk).where(ContentChunk.document_id == doc_id)
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


async def test_missing_current_version_fails(session: AsyncSession, fake_llm: LlmClient) -> None:
    """현재 버전에 대응하는 첨부 행이 없으면 failed(버전 없음) — 벡터는 첨부만 색인(ADR-0016)."""
    from liviq_db.models import Code, CodeGroup, Tenant

    tenant = Tenant(name="t", status="active")
    session.add(tenant)
    await session.flush()
    group = CodeGroup(
        tenant_id=tenant.id, group_key="DOC_CATEGORY", name="문서 카테고리", is_system=True
    )
    session.add(group)
    await session.flush()
    code = Code(tenant_id=tenant.id, group_id=group.id, code="규약", label="규약")
    session.add(code)
    await session.flush()
    doc = Document(
        tenant_id=tenant.id,
        title="x",
        category_code_id=code.id,
        visibility="ALL",
        version=1,
        index_status="pending",
    )
    session.add(doc)
    await session.flush()

    result = await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(b"..."),  # type: ignore[arg-type]
        document_id=doc.id,
        tenant_id=tenant.id,
    )
    assert result.status == "failed"
    assert result.error == "버전 없음"
    status = await session.scalar(select(Document.index_status).where(Document.id == doc.id))
    assert status == "failed"
