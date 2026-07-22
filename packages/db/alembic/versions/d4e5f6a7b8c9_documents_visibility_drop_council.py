"""documents visibility: COUNCIL 제거 backfill → ADMIN

COUNCIL 역할은 H7-2(ADR-0014)에서 이미 제거됐고, COUNCIL visibility는 관리자(MANAGER·STAFF)만
인용해 왔으므로 ADMIN과 동작이 동일한 죽은 옵션이었다. visibility enum에서 COUNCIL을 제거하며
기존 COUNCIL 문서를 ADMIN으로 이관해 인용 동작을 보존한다. visibility는 String 컬럼(CHECK 제약
없음)이라 타입 변경은 불필요하다.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-22 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE documents SET visibility = 'ADMIN' WHERE visibility = 'COUNCIL'")


def downgrade() -> None:
    # no-op: COUNCIL→ADMIN 이관은 되돌릴 수 없다(이관 후 원래 COUNCIL이던 행을 구분 불가).
    pass
