"""parking_assignments — 세대 배정 주차면 + 표준 tenant RLS (H9-5)

주차장 대시보드의 배정 주차면(세대당 다건, UNIQUE 없음). 차량번호는 plate_enc(AES-256-GCM
봉투 암호문)만 저장 — 평문 금지(규칙 2). 표준 tenant 격리 RLS(FORCE) + liviq_app
GRANT(SELECT/INSERT/UPDATE/DELETE). 시드 없음. downgrade는 테이블 drop(정책·GRANT·인덱스 동반 소멸).

Revision ID: c2d3e4f5a6b7
Revises: a9b1c2d3e4f5
Create Date: 2026-07-25 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "a9b1c2d3e4f5"
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
        "parking_assignments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("location_code", sa.String(), nullable=True),
        sa.Column("plate_enc", sa.LargeBinary(), nullable=True),
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
            name=op.f("fk_parking_assignments_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "household_id"],
            ["households.tenant_id", "households.id"],
            name="fk_parking_assignments_household",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parking_assignments")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_parking_assignments_tenant_id_id"),
    )
    op.create_index("ix_parking_assignments_household", "parking_assignments", ["household_id"])
    op.create_index(
        "ix_parking_assignments_tenant_household",
        "parking_assignments",
        ["tenant_id", "household_id"],
    )
    _enable_tenant_rls("parking_assignments")


def downgrade() -> None:
    op.drop_table("parking_assignments")  # 정책·GRANT·인덱스는 테이블과 함께 소멸
