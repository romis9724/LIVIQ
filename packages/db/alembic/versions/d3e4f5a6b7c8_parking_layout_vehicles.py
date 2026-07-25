"""parking_layouts·parking_vehicles — 지하주차장 배치도 + 입주민 차량 (H9-5)

배치도는 단지당 1행 JSONB(UNIQUE(tenant_id) — 전량 교체), 차량은 세대당 다건(UNIQUE 없음).
차량번호는 plate_enc(bytea) 봉투 암호문만 저장 — 평문 컬럼 없음(규칙 2). 두 테이블 모두 표준
tenant 격리 RLS(FORCE) + liviq_app GRANT. 시드는 seed_parking.py(운영은 업로드/등록 경로).
downgrade는 테이블 drop(정책·GRANT 동반 소멸).

Revision ID: d3e4f5a6b7c8
Revises: a9b1c2d3e4f5
Create Date: 2026-07-25 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3e4f5a6b7c8"
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
        "parking_layouts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("fk_parking_layouts_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parking_layouts")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_parking_layouts_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", name="uq_parking_layouts_tenant"),
    )
    _enable_tenant_rls("parking_layouts")

    op.create_table(
        "parking_vehicles",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("plate_enc", sa.LargeBinary(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("is_ev", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
            name=op.f("fk_parking_vehicles_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "household_id"],
            ["households.tenant_id", "households.id"],
            name="fk_parking_vehicles_household",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parking_vehicles")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_parking_vehicles_tenant_id_id"),
    )
    op.create_index("ix_parking_vehicles_household", "parking_vehicles", ["household_id"])
    op.create_index(
        "ix_parking_vehicles_tenant_household", "parking_vehicles", ["tenant_id", "household_id"]
    )
    _enable_tenant_rls("parking_vehicles")


def downgrade() -> None:
    op.drop_table("parking_vehicles")  # 정책·GRANT·인덱스는 테이블과 함께 소멸
    op.drop_table("parking_layouts")
