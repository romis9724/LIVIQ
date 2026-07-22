"""document board — versioned attachments + generalized content_chunks

H8-2 (ADR-0016): 문서관리 게시판 전환.
- documents: body 추가, storage_key·content_hash 제거(버전 테이블로 이동), content_hash partial unique 제거.
- document_versions 신설 — 첨부 버전 이력(다운로드 전용).
- document_chunks → content_chunks rename + document|notice 다형(source_type·notice_id·CHECK, H8-3 대비).
- citations.chunk_id FK를 content_chunks로 재지정(SET NULL 유지).
스키마(create/drop)와 RLS·GRANT(op.execute)를 한 마이그레이션에 둔다(357f10ab881d 스타일).

기존 데이터는 폐기(ADR-0016 승인) — documents·청크 전량 삭제, 복원 로직 없음.

Revision ID: d7e8f9a0b1c2
Revises: b2c3d4e5f6a7
Create Date: 2026-07-22 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"
_SOURCE_CHECK = (
    "(source_type = 'document') = (document_id IS NOT NULL) "
    "AND (source_type = 'notice') = (notice_id IS NOT NULL)"
)


def upgrade() -> None:
    # 기존 데이터 폐기(ADR-0016) — citations 근거 링크 해제 후 문서·청크 제거.
    op.execute("UPDATE citations SET chunk_id = NULL, document_id = NULL")

    # citations.chunk_id FK는 content_chunks로 재지정 예정 — 먼저 해제.
    op.drop_constraint("fk_citations_chunk", "citations", type_="foreignkey")

    # 구 청크 테이블 제거(document 전용 스키마 — 정책·GRANT는 테이블과 함께 소멸).
    op.drop_index(
        "ix_document_chunks_embedding_hnsw",
        table_name="document_chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_document_chunks_tenant_document", table_name="document_chunks")
    op.drop_table("document_chunks")

    op.execute("DELETE FROM documents")

    # documents: 첨부·해시를 버전 테이블로 이동, 본문(설명용) 추가.
    op.drop_index(
        "uq_documents_content_hash_active",
        table_name="documents",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.add_column("documents", sa.Column("body", sa.Text(), nullable=True))
    op.drop_column("documents", "storage_key")
    op.drop_column("documents", "content_hash")

    # document_versions — 버전별 첨부 메타(append-only 이력).
    op.create_table(
        "document_versions",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_document_versions_document",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_document_versions_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "tenant_id", "document_id", "version", name="uq_document_versions_document_version"
        ),
    )

    # content_chunks — document|notice 다형 청크(H8-3 대비 — 이번엔 document만 사용).
    op.create_table(
        "content_chunks",
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("notice_id", sa.UUID(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("heading", sa.String(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("clause", sa.String(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(dim=1024), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_SOURCE_CHECK, name="ck_content_chunks_source_polymorphism"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_content_chunks_document",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "notice_id"],
            ["notices.tenant_id", "notices.id"],
            name="fk_content_chunks_notice",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_content_chunks_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_chunks")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_content_chunks_tenant_id_id"),
    )
    op.create_index(
        "ix_content_chunks_embedding_hnsw",
        "content_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_content_chunks_tenant_document",
        "content_chunks",
        ["tenant_id", "document_id"],
        unique=False,
    )

    # citations.chunk_id FK 재지정 → content_chunks (chunk 삭제 시 chunk_id만 NULL, §4.3).
    op.create_foreign_key(
        "fk_citations_chunk",
        "citations",
        "content_chunks",
        ["tenant_id", "chunk_id"],
        ["tenant_id", "id"],
        ondelete="SET NULL (chunk_id)",
    )

    _apply_rls_and_grants()


def _apply_rls_and_grants() -> None:
    """content_chunks·document_versions에 표준 tenant 격리 + role GRANT(eaf86de665b0 패턴)."""
    for table in ("content_chunks", "document_versions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
            f"USING (tenant_id = {_CURRENT_TENANT}) "
            f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO liviq_app")

    # 워커: 재색인 = 기존 청크 delete 후 재삽입이므로 DELETE까지 필요
    # (구 document_chunks는 DELETE 누락 — 로컬 superuser 접속이라 잠복했던 결함, 여기서 교정).
    # document_versions는 현재 버전 storage_key 조회용 읽기만.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON content_chunks TO liviq_worker")
    op.execute("GRANT SELECT ON document_versions TO liviq_worker")


def downgrade() -> None:
    # 데이터 복원 불가(폐기됨) — 스키마만 역방향 복원.
    op.drop_constraint("fk_citations_chunk", "citations", type_="foreignkey")

    op.drop_index(
        "ix_content_chunks_embedding_hnsw",
        table_name="content_chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_content_chunks_tenant_document", table_name="content_chunks")
    op.drop_table("content_chunks")  # 정책·GRANT 함께 소멸
    op.drop_table("document_versions")

    op.add_column("documents", sa.Column("storage_key", sa.String(), nullable=False))
    op.add_column("documents", sa.Column("content_hash", sa.String(), nullable=False))
    op.drop_column("documents", "body")
    op.create_index(
        "uq_documents_content_hash_active",
        "documents",
        ["tenant_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "document_chunks",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("heading", sa.String(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("clause", sa.String(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(dim=1024), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_document_chunks_document",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_document_chunks_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_document_chunks_tenant_id_id"),
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_document_chunks_tenant_document",
        "document_chunks",
        ["tenant_id", "document_id"],
        unique=False,
    )

    op.execute("ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON document_chunks FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON document_chunks TO liviq_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON document_chunks TO liviq_worker")

    op.create_foreign_key(
        "fk_citations_chunk",
        "citations",
        "document_chunks",
        ["tenant_id", "chunk_id"],
        ["tenant_id", "id"],
        ondelete="SET NULL (chunk_id)",
    )
