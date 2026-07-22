"""문서 게시판·버전·벡터 — documents·document_versions·content_chunks (docs/03 §4.2, ADR-0016).

문서 = 제목 + 본문(설명용, 임베딩 안 함) + 첨부 1개(버전 이력). 재업로드 = version+1 + 재인제스트.
청크는 공지 소스까지 수용하는 content_chunks로 일반화(H8-3 대비 — document|notice 다형).
"""

from __future__ import annotations

import datetime
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    """게시글 메타. 첨부·해시는 document_versions로 이동. soft delete 대상(§3)."""

    __tablename__ = "documents"
    __table_args__ = (
        tenant_id_unique("documents"),
        tenant_fk("uploaded_by", "users", name="fk_documents_uploaded_by"),
    )

    title: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)  # 규약|회의록|공지|지침|매뉴얼
    visibility: Mapped[str] = mapped_column(String, nullable=False)  # ALL|RESIDENT|ADMIN
    body: Mapped[str | None] = mapped_column(Text, nullable=True)  # 설명용 본문 — 임베딩 안 함
    # 현재 버전 번호(document_versions 최신과 일치).
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # pending|indexing|indexed|failed
    index_status: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentVersion(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """첨부 버전 이력. 재업로드마다 append(다운로드 전용 — 롤백 없음, ADR-0016)."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "document_id", "version", name="uq_document_versions_document_version"
        ),
        tenant_fk("document_id", "documents", name="fk_document_versions_document"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class ContentChunk(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """청크 + 임베딩(document|notice 다형). 재색인 시 삭제·재생성(citations.chunk_id는 SET NULL)."""

    __tablename__ = "content_chunks"
    __table_args__ = (
        tenant_id_unique("content_chunks"),
        tenant_fk("document_id", "documents", name="fk_content_chunks_document"),
        tenant_fk("notice_id", "notices", name="fk_content_chunks_notice"),
        # 소스 다형 정합성 — document는 document_id, notice는 notice_id만 채운다.
        CheckConstraint(
            "(source_type = 'document') = (document_id IS NOT NULL) "
            "AND (source_type = 'notice') = (notice_id IS NOT NULL)",
            name="source_polymorphism",
        ),
        Index("ix_content_chunks_tenant_document", "tenant_id", "document_id"),
        # 벡터 ANN — cosine. 검색 전 tenant_id·visibility·source_type 선필터(§4.2·§7).
        Index(
            "ix_content_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    source_type: Mapped[str] = mapped_column(String, nullable=False)  # document|notice
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[str | None] = mapped_column(String, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clause: Mapped[str | None] = mapped_column(String, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
