"""공지·문서 코드 적용 — notices 부가 필드 + documents.source_type→category_code_id (H8-6, ADR-0017)

notices에 category_code_id(NULL)·event_start·event_end·target_buildings·keywords를 추가하고
NOTICE_CATEGORY 그룹 코드로 composite FK(RESTRICT)를 건다. documents는 하드코딩 source_type을
DOC_CATEGORY 그룹 코드 참조(category_code_id NOT NULL)로 전환한다 — 기존 데이터는 label 일치로
매핑 후 NOT NULL 확정, source_type 컬럼 drop. 두 FK 모두 (tenant_id, category_code_id)→
codes(tenant_id, id) RESTRICT라 참조 중 코드 삭제는 DB가 거부(API 409, 규칙 3 cross-tenant 차단).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-22 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_notice_columns() -> None:
    op.add_column("notices", sa.Column("category_code_id", sa.UUID(), nullable=True))
    op.add_column("notices", sa.Column("event_start", sa.Date(), nullable=True))
    op.add_column("notices", sa.Column("event_end", sa.Date(), nullable=True))
    op.add_column("notices", sa.Column("target_buildings", postgresql.JSONB(), nullable=True))
    op.add_column("notices", sa.Column("keywords", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_notices_category_code",
        "notices",
        "codes",
        ["tenant_id", "category_code_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_notices_tenant_category", "notices", ["tenant_id", "category_code_id"])


def _convert_document_source_type() -> None:
    # source_type enum → DOC_CATEGORY 코드 참조. 우선 NULL로 추가 후 label 일치 매핑.
    op.add_column("documents", sa.Column("category_code_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE documents SET category_code_id = (
            SELECT c.id FROM codes c
            JOIN code_groups g ON g.id = c.group_id AND g.tenant_id = c.tenant_id
            WHERE g.tenant_id = documents.tenant_id
              AND g.group_key = 'DOC_CATEGORY'
              AND c.code = documents.source_type
        )
        """
    )
    op.alter_column("documents", "category_code_id", nullable=False)
    op.create_foreign_key(
        "fk_documents_category_code",
        "documents",
        "codes",
        ["tenant_id", "category_code_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_documents_tenant_category", "documents", ["tenant_id", "category_code_id"])
    op.drop_column("documents", "source_type")


def upgrade() -> None:
    _add_notice_columns()
    _convert_document_source_type()


def downgrade() -> None:
    # documents: category_code_id → source_type(코드 label 복원). seed는 code=label이라 label 사용.
    op.add_column("documents", sa.Column("source_type", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE documents SET source_type = (
            SELECT c.label FROM codes c
            WHERE c.tenant_id = documents.tenant_id AND c.id = documents.category_code_id
        )
        """
    )
    op.alter_column("documents", "source_type", nullable=False)
    op.drop_index("ix_documents_tenant_category", table_name="documents")
    op.drop_constraint("fk_documents_category_code", "documents", type_="foreignkey")
    op.drop_column("documents", "category_code_id")

    op.drop_index("ix_notices_tenant_category", table_name="notices")
    op.drop_constraint("fk_notices_category_code", "notices", type_="foreignkey")
    op.drop_column("notices", "keywords")
    op.drop_column("notices", "target_buildings")
    op.drop_column("notices", "event_end")
    op.drop_column("notices", "event_start")
    op.drop_column("notices", "category_code_id")
