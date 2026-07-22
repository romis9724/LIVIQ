"""code registry — code_groups·codes + 표준 tenant RLS + 기존 단지 기본 코드 시드 (H8-4, ADR-0017)

공통 코드 레지스트리(docs/03 §4.10). 두 테이블 모두 표준 tenant 격리 RLS(FORCE) + liviq_app
GRANT(SELECT/INSERT/UPDATE/DELETE). 스키마 생성 후 기존 단지(시스템 테넌트 제외)에 기본 코드를
시드한다 — 시드 값은 liviq_db.codes_seed.DEFAULT_CODE_GROUPS가 단일 출처(단지 생성 API와 공유).
신규 DB(테넌트 0개)는 시드 루프가 no-op. downgrade는 테이블 drop(정책·GRANT 동반 소멸).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-22 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from liviq_db.codes_seed import DEFAULT_CODE_GROUPS

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"
# 시스템 테넌트(SYS_ADMIN 소속, 단지 아님) — apps/api/app/config.SYSTEM_TENANT_ID와 동일 상수.
_SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO liviq_app")


def _create_code_groups() -> None:
    op.create_table(
        "code_groups",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("group_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_code_groups_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_groups")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_code_groups_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "group_key", name="uq_code_groups_tenant_group_key"),
    )
    _enable_tenant_rls("code_groups")


def _create_codes() -> None:
    op.create_table(
        "codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_codes_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["code_groups.tenant_id", "code_groups.id"],
            name="fk_codes_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["codes.tenant_id", "codes.id"],
            name="fk_codes_parent",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_codes")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_codes_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "group_id", "code", name="uq_codes_tenant_group_code"),
    )
    op.create_index("ix_codes_tenant_group", "codes", ["tenant_id", "group_id", "sort_order"])
    _enable_tenant_rls("codes")


def _seed_existing_tenants() -> None:
    """기존 단지에 기본 코드 시드(시스템 테넌트 제외). 마이그레이션은 owner(RLS 우회)로 실행.

    시드 값은 DEFAULT_CODE_GROUPS 단일 출처. 신규 DB는 tenants가 비어 no-op(단지 생성 API가 시드).
    """
    conn = op.get_bind()
    tenant_ids = [
        row[0]
        for row in conn.execute(
            sa.text("SELECT id FROM tenants WHERE id <> :sys"), {"sys": _SYSTEM_TENANT_ID}
        )
    ]
    for tenant_id in tenant_ids:
        for group in DEFAULT_CODE_GROUPS:
            group_id = conn.execute(
                sa.text(
                    "INSERT INTO code_groups (tenant_id, group_key, name, is_system) "
                    "VALUES (:t, :k, :n, true) RETURNING id"
                ),
                {"t": tenant_id, "k": group.group_key, "n": group.name},
            ).scalar_one()
            for order, code in enumerate(group.codes):
                conn.execute(
                    sa.text(
                        "INSERT INTO codes (tenant_id, group_id, code, label, sort_order) "
                        "VALUES (:t, :g, :c, :l, :o)"
                    ),
                    {"t": tenant_id, "g": group_id, "c": code.code, "l": code.label, "o": order},
                )


def upgrade() -> None:
    _create_code_groups()
    _create_codes()
    _seed_existing_tenants()


def downgrade() -> None:
    op.drop_index("ix_codes_tenant_group", table_name="codes")
    op.drop_table("codes")  # 정책·GRANT는 테이블과 함께 소멸
    op.drop_table("code_groups")
