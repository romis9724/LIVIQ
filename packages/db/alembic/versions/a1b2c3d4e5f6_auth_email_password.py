"""auth email+password (verify·invite·reset tokens)

H7-1: 자체 이메일+비밀번호 인증 배선(ADR-0014, docs/06 §2).
users에 password_hash·email_verified_at 추가 + auth_tokens 신설.
RLS·GRANT는 autogenerate 대상이 아니라 수기 작성(357f10ab881d 스타일 준수).

Revision ID: a1b2c3d4e5f6
Revises: f7a1c2d3e4b5
Create Date: 2026-07-21 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f7a1c2d3e4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # ── users 인증 컬럼(ADR-0014) ─────────────────────────────────────────
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )

    # ── auth_tokens(1회용 토큰, ADR-0014) ─────────────────────────────────
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_auth_tokens_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_auth_tokens_user",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
    )
    # token_hash 전역 unique — 클릭 시점 tenant 확정 전 전역 조회(auth_lookup)용.
    op.create_index("uq_auth_tokens_token_hash", "auth_tokens", ["token_hash"], unique=True)

    # tenant_isolation(표준) + auth_lookup permissive SELECT(token_hash 전역 조회).
    # 소진(used_at UPDATE)은 콜백이 SET app.tenant_id 후 tenant_isolation 하에서 수행.
    op.execute("ALTER TABLE auth_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE auth_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON auth_tokens FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    op.execute(
        "CREATE POLICY auth_lookup ON auth_tokens FOR SELECT "
        "USING (current_setting('app.auth_lookup', true) = 'on')"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON auth_tokens TO liviq_app")


def downgrade() -> None:
    # 정책·GRANT는 테이블과 함께 소멸.
    op.drop_index("uq_auth_tokens_token_hash", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "password_hash")
