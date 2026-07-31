"""parking_vehicles 점유 영속화 — spot_no·entry_at·household_id 완화 (H16-1, 03 §4.11)

프론트 시뮬레이션이 갖고 있던 점유 상태를 DB로 옮긴다. `spot_no`(layout spots.no)와
`entry_at`(입차시각)은 함께만 의미가 있고, 둘 다 NULL이면 "등록만 되고 미주차"다.
`household_id`는 NULL 완화 — 명부에 없는 외부 차량(방문·방치)도 면을 점유한다.
기존 composite FK(fk_parking_vehicles_household, ON DELETE CASCADE)는 그대로 두고
nullable만 바꾼다(NULL이면 MATCH SIMPLE 규칙으로 FK 미검증).

한 면에 두 대가 서지 못하도록 부분 유니크 `(tenant_id, spot_no) WHERE spot_no IS NOT NULL`.
미주차 행이 여럿이어도 NULL은 유니크에 걸리지 않는다. 컬럼·인덱스 추가라 기존 tenant RLS
정책(tenant_isolation FOR ALL, d3e4f5a6b7c8)·GRANT는 영향 없다.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-31 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIQUE_SPOT = "uq_parking_vehicles_tenant_spot"


def upgrade() -> None:
    op.add_column("parking_vehicles", sa.Column("spot_no", sa.String(), nullable=True))
    op.add_column(
        "parking_vehicles", sa.Column("entry_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column("parking_vehicles", "household_id", existing_type=sa.UUID(), nullable=True)
    op.create_index(
        _UNIQUE_SPOT,
        "parking_vehicles",
        ["tenant_id", "spot_no"],
        unique=True,
        postgresql_where=sa.text("spot_no IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_UNIQUE_SPOT, table_name="parking_vehicles")
    # household_id NOT NULL 복원은 외부 차량 행이 남아있으면 실패한다 — 먼저 지운다.
    op.execute("DELETE FROM parking_vehicles WHERE household_id IS NULL")
    op.alter_column("parking_vehicles", "household_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("parking_vehicles", "entry_at")
    op.drop_column("parking_vehicles", "spot_no")
