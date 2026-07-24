"""household_geometries — 세대 3D 폴리곤 + 표준 tenant RLS (H9-1, ADR-0019)

단지 트윈 렌더 전용 geometry(units.json 업로드 산물, docs/03 §4.8). 표준 tenant 격리
RLS(FORCE) + liviq_app GRANT(SELECT/INSERT/UPDATE/DELETE). 시드 없음 — geometry는 업로드로만
채운다. downgrade는 테이블 drop(정책·GRANT 동반 소멸).

Revision ID: a9b1c2d3e4f5
Revises: c4a7e2f1b9d3
Create Date: 2026-07-24 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9b1c2d3e4f5"
down_revision: str | None = "c4a7e2f1b9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO liviq_app")


def upgrade() -> None:
    op.create_table(
        "household_geometries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("polygon_2d", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("polygon_3d", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("base_z", sa.Numeric(), nullable=False),
        sa.Column("floor_height", sa.Numeric(), nullable=False),
        sa.Column("area_m2", sa.Numeric(), nullable=True),
        sa.Column("unit_type_label", sa.String(), nullable=True),
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
            name=op.f("fk_household_geometries_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "household_id"],
            ["households.tenant_id", "households.id"],
            name="fk_household_geometries_household",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_household_geometries")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_household_geometries_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "household_id", name="uq_household_geometries_tenant_household"
        ),
    )
    _enable_tenant_rls("household_geometries")


def downgrade() -> None:
    op.drop_table("household_geometries")  # 정책·GRANT는 테이블과 함께 소멸
