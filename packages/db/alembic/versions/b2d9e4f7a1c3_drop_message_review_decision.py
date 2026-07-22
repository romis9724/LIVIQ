"""drop message review decision columns

H8-7: AI 검수 큐 제거(ADR-0015 개정 노트) — messages의 사후 검수 결정 컬럼
(reviewed_by·reviewed_at·review_note)을 드롭한다. f7a1c2d3e4b5의 역이다.
review_status·confidence는 저신뢰 플래그(대시보드 검수 필요율)로 유지.
컬럼만 드롭(테이블·RLS·GRANT 불변 — messages는 이미 liviq_app DML 대상).

Revision ID: b2d9e4f7a1c3
Revises: f6a7b8c9d0e1
Create Date: 2026-07-22 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2d9e4f7a1c3"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("messages", "review_note")
    op.drop_column("messages", "reviewed_at")
    op.drop_column("messages", "reviewed_by")


def downgrade() -> None:
    op.add_column("messages", sa.Column("reviewed_by", sa.UUID(), nullable=True))
    op.add_column(
        "messages", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("messages", sa.Column("review_note", sa.Text(), nullable=True))
