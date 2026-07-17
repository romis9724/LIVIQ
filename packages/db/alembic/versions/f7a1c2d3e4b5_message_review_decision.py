"""message review decision columns

H2-6: 사후 검수 결정 기록 — messages에 reviewed_by·reviewed_at·review_note 신설(docs/03 §4.3).
컬럼만 추가(테이블·RLS·GRANT 불변 — messages는 이미 liviq_app DML 대상).

Revision ID: f7a1c2d3e4b5
Revises: c1a2b3d4e5f6
Create Date: 2026-07-17 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a1c2d3e4b5"
down_revision: str | None = "c1a2b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("reviewed_by", sa.UUID(), nullable=True))
    op.add_column(
        "messages", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("messages", sa.Column("review_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "review_note")
    op.drop_column("messages", "reviewed_at")
    op.drop_column("messages", "reviewed_by")
