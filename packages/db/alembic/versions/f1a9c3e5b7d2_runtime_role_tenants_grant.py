"""runtime role tenants grant

H10-2 — 런타임이 owner(superuser)가 아니라 `liviq_app`으로 접속하게 되면서 드러난 GRANT 누락 보강.
`tenants`는 RLS 예외 테이블이라 권한만이 방어선이다(docs/03 §5 전역·예외 테이블 표):

- INSERT: 단지 생성(`POST /admin/tenants`, SYS_ADMIN)
- UPDATE: 단지 비활성/재활성(`status` 전환)
- DELETE: **계정이 없는** 단지 삭제(`DELETE /admin/tenants/{id}` — 계정이 있으면 라우터가 409로 먼저 막는다)

DELETE를 처음엔 제외했다가 추가했다 — 실접속 롤로 라이브 여정을 돌려보니 빈 단지 삭제가
`permission denied for table tenants`(500)로 깨졌다. owner 접속에서는 드러나지 않는 종류의 갭이다.

Revision ID: f1a9c3e5b7d2
Revises: d3e4f5a6b7c8
Create Date: 2026-07-26 21:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f1a9c3e5b7d2"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT INSERT, UPDATE, DELETE ON tenants TO liviq_app")


def downgrade() -> None:
    op.execute("REVOKE INSERT, UPDATE, DELETE ON tenants FROM liviq_app")
