"""parking_occupancy — 면 점유 단일 사실 원천(SoR) (H15-4, ADR-0023)

프론트 `simulateParking()`가 매 렌더 합성하던 점유를 PG로 영속화한다(면당 1행·전량 교체·표준
tenant RLS). 입주민 차는 parking_vehicles composite FK(ON DELETE CASCADE), 외부/방문차는
external_plate_enc(bytea) 봉투 암호문만 — 평문 컬럼 없음(규칙 2). is_external 분기 무결성은
CHECK로 강제(둘 중 정확히 하나의 점유자). 시더(owner)가 씀 · api(liviq_app)·worker(liviq_worker)는
SELECT만(도구·gen_labels 읽기 전용). downgrade는 테이블 drop(정책·GRANT·제약 동반 소멸).

Revision ID: a4b5c6d7e8f9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-31 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"

_OCCUPANT_CHECK = (
    "(is_external = false AND parking_vehicle_id IS NOT NULL AND external_plate_enc IS NULL) "
    "OR (is_external = true AND parking_vehicle_id IS NULL AND external_plate_enc IS NOT NULL)"
)


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    # 점유는 시더(owner)만 씀 — 도구·gen_labels는 읽기 전용(SELECT).
    op.execute(f"GRANT SELECT ON {table} TO liviq_app")
    op.execute(f"GRANT SELECT ON {table} TO liviq_worker")


def upgrade() -> None:
    op.create_table(
        "parking_occupancy",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("spot_no", sa.Text(), nullable=False),
        sa.Column("is_external", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("parking_vehicle_id", sa.UUID(), nullable=True),
        sa.Column("external_plate_enc", sa.LargeBinary(), nullable=True),
        sa.Column("parked_hours", sa.Float(), nullable=True),
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
            name=op.f("fk_parking_occupancy_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parking_vehicle_id"],
            ["parking_vehicles.tenant_id", "parking_vehicles.id"],
            name="fk_parking_occupancy_vehicle",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(_OCCUPANT_CHECK, name="ck_parking_occupancy_occupant"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_parking_occupancy")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_parking_occupancy_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "spot_no", name="uq_parking_occupancy_tenant_spot"),
    )
    op.create_index("ix_parking_occupancy_tenant", "parking_occupancy", ["tenant_id"])
    _enable_tenant_rls("parking_occupancy")


def downgrade() -> None:
    op.drop_table("parking_occupancy")  # 정책·GRANT·인덱스·제약은 테이블과 함께 소멸
