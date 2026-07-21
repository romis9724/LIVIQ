"""users must_change_password (SYS_ADMIN 임시 비밀번호 강제 변경)

H7-2: 부트스트랩 SYS_ADMIN은 임시 비밀번호로 생성되고 첫 로그인 시 변경을 강제한다
(ADR-0014). must_change_password=True인 세션은 password-change·logout·me만 허용
(가드는 app.deps.get_context). 순수 컬럼 추가라 RLS·GRANT 변경 없음.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-21 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
