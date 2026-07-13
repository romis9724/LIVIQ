"""문서·벡터 (RAG) — documents·document_chunks (docs/03 §4.2)."""

from __future__ import annotations

import datetime
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import (
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    tenant_fk,
    tenant_id_unique,
)

# bge-m3 임베딩 차원 고정(§4.2). 변경 = 전량 재색인 마이그레이션 이벤트.
EMBEDDING_DIM = 1024


class Document(IdMixin, TenantMixin, TimestampMixin, Base):
    """원문 메타. soft delete 대상(§3)."""

    __tablename__ = "documents"
    __table_args__ = (
        tenant_id_unique("documents"),
        # 멱등 인제스트 — 삭제 후 재등록 허용 위해 partial unique(§3)
        Index(
            "uq_documents_content_hash_active",
            "tenant_id",
            "content_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        tenant_fk("uploaded_by", "users", name="fk_documents_uploaded_by"),
    )

    title: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)  # 규약|회의록|공지|지침|매뉴얼
    visibility: Mapped[str] = mapped_column(String, nullable=False)  # ALL|RESIDENT|ADMIN|COUNCIL
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # pending|indexing|indexed|failed
    index_status: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentChunk(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """청크 + 임베딩. 재색인 시 삭제·재생성(citations.chunk_id는 SET NULL)."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        tenant_id_unique("document_chunks"),
        tenant_fk("document_id", "documents", name="fk_document_chunks_document"),
        Index("ix_document_chunks_tenant_document", "tenant_id", "document_id"),
        # 벡터 ANN — cosine. 검색 전 tenant_id·visibility 선필터(§4.2·§7).
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[str | None] = mapped_column(String, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clause: Mapped[str | None] = mapped_column(String, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
