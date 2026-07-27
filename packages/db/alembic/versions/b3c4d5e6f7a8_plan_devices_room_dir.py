"""plan_devices.room·dir — 방 축 질의·벽 방향 마커 (H13-3, docs/03 §4.8)

room은 device_type='room' 행의 방 이름(중심좌표) 또는 일반 장치가 속한 방 이름,
dir은 벽 부착 장치의 방향(up|down|left|right, NULL=원형 마커)이다. 둘 다 nullable —
기존 0행 테이블에 컬럼만 추가하므로 백필 불필요. 기존 tenant RLS 정책·GRANT는 그대로다.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-07-27 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_devices", sa.Column("room", sa.Text(), nullable=True))
    op.add_column("plan_devices", sa.Column("dir", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("plan_devices", "dir")
    op.drop_column("plan_devices", "room")
