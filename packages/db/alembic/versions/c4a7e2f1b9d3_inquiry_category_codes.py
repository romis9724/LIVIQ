"""민원 개편 — inquiry_categories 폐기·category_code_id 전환·ai_priority→priority (H8-9, ADR-0018)

AI 분류를 제거하고 민원 분류를 공통 코드 그룹 INQUIRY_CATEGORY로 흡수한다(ADR-0017·0018).
기존 단지에 INQUIRY_CATEGORY 그룹+코드를 시드하고, inquiries.category_id(inquiry_categories.name
참조)를 codes.label 일치로 category_code_id에 backfill한 뒤 구 FK 컬럼(category_id·
ai_suggested_category_id)을 drop, inquiry_categories 테이블을 폐기한다. ai_priority는 수동
priority로 rename한다. category_code_id는 (tenant_id, category_code_id)→codes(tenant_id, id)
RESTRICT라 참조 중 코드 삭제를 DB가 거부(규칙 3 cross-tenant 차단).

Revision ID: c4a7e2f1b9d3
Revises: b2d9e4f7a1c3
Create Date: 2026-07-23 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from liviq_db.codes_seed import DEFAULT_CODE_GROUPS

revision: str = "c4a7e2f1b9d3"
down_revision: str | None = "b2d9e4f7a1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GROUP_KEY = "INQUIRY_CATEGORY"
_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"
# 시스템 테넌트(SYS_ADMIN 소속, 단지 아님) — apps/api/app/config.SYSTEM_TENANT_ID와 동일 상수.
_SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def _inquiry_category_seed() -> tuple[str, tuple[tuple[str, str], ...]]:
    """DEFAULT_CODE_GROUPS(단일 출처)에서 INQUIRY_CATEGORY 그룹 name·코드를 추출."""
    group = next(g for g in DEFAULT_CODE_GROUPS if g.group_key == _GROUP_KEY)
    return group.name, tuple((c.code, c.label) for c in group.codes)


def _seed_existing_tenants() -> None:
    """기존 단지에 INQUIRY_CATEGORY 그룹+코드 시드(시스템 테넌트 제외). 마이그레이션은 owner로 실행.

    신규 DB(tenants 0개)는 no-op — 단지 생성 API가 시드(seed_default_codes).
    """
    conn = op.get_bind()
    name, codes = _inquiry_category_seed()
    tenant_ids = [
        row[0]
        for row in conn.execute(
            sa.text("SELECT id FROM tenants WHERE id <> :sys"), {"sys": _SYSTEM_TENANT_ID}
        )
    ]
    for tenant_id in tenant_ids:
        group_id = conn.execute(
            sa.text(
                "INSERT INTO code_groups (tenant_id, group_key, name, is_system) "
                "VALUES (:t, :k, :n, true) RETURNING id"
            ),
            {"t": tenant_id, "k": _GROUP_KEY, "n": name},
        ).scalar_one()
        for order, (code, label) in enumerate(codes):
            conn.execute(
                sa.text(
                    "INSERT INTO codes (tenant_id, group_id, code, label, sort_order) "
                    "VALUES (:t, :g, :c, :l, :o)"
                ),
                {"t": tenant_id, "g": group_id, "c": code, "l": label, "o": order},
            )


def upgrade() -> None:
    _seed_existing_tenants()

    # category_id(inquiry_categories.name) → INQUIRY_CATEGORY 코드(label 일치)로 backfill.
    op.add_column("inquiries", sa.Column("category_code_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE inquiries SET category_code_id = (
            SELECT c.id FROM codes c
            JOIN code_groups g ON g.id = c.group_id AND g.tenant_id = c.tenant_id
            JOIN inquiry_categories ic
              ON ic.id = inquiries.category_id AND ic.tenant_id = inquiries.tenant_id
            WHERE g.tenant_id = inquiries.tenant_id
              AND g.group_key = 'INQUIRY_CATEGORY'
              AND c.label = ic.name
        )
        WHERE inquiries.category_id IS NOT NULL
        """
    )
    op.create_foreign_key(
        "fk_inquiries_category_code",
        "inquiries",
        "codes",
        ["tenant_id", "category_code_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_inquiries_tenant_category", "inquiries", ["tenant_id", "category_code_id"])

    # 구 AI 분류 컬럼·FK 폐기.
    op.drop_constraint("fk_inquiries_ai_category", "inquiries", type_="foreignkey")
    op.drop_constraint("fk_inquiries_category", "inquiries", type_="foreignkey")
    op.drop_column("inquiries", "ai_suggested_category_id")
    op.drop_column("inquiries", "category_id")
    op.alter_column("inquiries", "ai_priority", new_column_name="priority")

    op.drop_table("inquiry_categories")


def downgrade() -> None:
    # inquiry_categories 재생성(초기 스키마 정의 + tenant RLS·GRANT). 데이터는 복원 안 함(best-effort).
    op.create_table(
        "inquiry_categories",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("default_assignee_role", sa.String(), nullable=True),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_inquiry_categories_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inquiry_categories")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inquiry_categories_tenant_id_id"),
    )
    op.execute("ALTER TABLE inquiry_categories ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE inquiry_categories FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON inquiry_categories FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON inquiry_categories TO liviq_app")

    op.alter_column("inquiries", "priority", new_column_name="ai_priority")
    op.add_column("inquiries", sa.Column("category_id", sa.UUID(), nullable=True))
    op.add_column("inquiries", sa.Column("ai_suggested_category_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_inquiries_category",
        "inquiries",
        "inquiry_categories",
        ["tenant_id", "category_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_inquiries_ai_category",
        "inquiries",
        "inquiry_categories",
        ["tenant_id", "ai_suggested_category_id"],
        ["tenant_id", "id"],
    )

    op.drop_index("ix_inquiries_tenant_category", table_name="inquiries")
    op.drop_constraint("fk_inquiries_category_code", "inquiries", type_="foreignkey")
    op.drop_column("inquiries", "category_code_id")

    # 기존 단지의 INQUIRY_CATEGORY 코드·그룹 제거(코드는 그룹 CASCADE로 함께 소멸).
    op.execute(
        "DELETE FROM code_groups WHERE group_key = 'INQUIRY_CATEGORY' "
        f"AND tenant_id <> '{_SYSTEM_TENANT_ID}'"
    )
