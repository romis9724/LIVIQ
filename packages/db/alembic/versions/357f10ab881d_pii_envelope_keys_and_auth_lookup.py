"""pii envelope keys and auth_lookup policy

H2-1: 봉투 암호화·명부 대조·auth 조회 배선(docs/03 §4.1·5·6, ADR-0010).
스키마(add_column·create_table)와 RLS·GRANT(op.execute)를 한 마이그레이션에 둔다 —
RLS/role/뷰는 autogenerate 대상이 아니므로 수기 작성(eaf86de665b0 스타일 준수).

Revision ID: 357f10ab881d
Revises: eaf86de665b0
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "357f10ab881d"
down_revision: str | None = "eaf86de665b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # ── pii_vault 보강(§4.1) ──────────────────────────────────────────────
    op.add_column("pii_vault", sa.Column("birth_date_hash", sa.String(), nullable=True))
    op.add_column(
        "pii_vault",
        sa.Column("key_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )

    # ── tenant_keys(per-tenant DEK, ADR-0010) ────────────────────────────
    op.create_table(
        "tenant_keys",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("dek_wrapped", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_keys_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_keys")),
        sa.UniqueConstraint(
            "tenant_id", "key_version", name="uq_tenant_keys_tenant_key_version"
        ),
    )

    # tenant_keys: 표준 격리 + FORCE. append-only — SELECT·INSERT만 GRANT(키 회전은
    # 새 key_version INSERT로만, UPDATE/DELETE 금지, §4.1·ADR-0010).
    op.execute("ALTER TABLE tenant_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_keys FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON tenant_keys FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    op.execute("GRANT SELECT, INSERT ON tenant_keys TO liviq_app")

    # ── users auth_lookup 정책(§5) ────────────────────────────────────────
    # OAuth 콜백의 login_id(google sub) 전역 조회는 tenant 확정 전이라 tenant_isolation을
    # 통과 못 한다. 콜백이 SET LOCAL app.auth_lookup='on' 한 트랜잭션에서만 SELECT 허용.
    # permissive라 tenant_isolation과 OR — 쓰기는 불가(FOR SELECT).
    op.execute(
        "CREATE POLICY auth_lookup ON users FOR SELECT "
        "USING (current_setting('app.auth_lookup', true) = 'on')"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS auth_lookup ON users")
    # tenant_keys 정책·GRANT는 테이블과 함께 소멸.
    op.drop_table("tenant_keys")
    op.drop_column("pii_vault", "key_version")
    op.drop_column("pii_vault", "birth_date_hash")
