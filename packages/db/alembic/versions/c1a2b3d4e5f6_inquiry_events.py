"""inquiry_events timeline table

H2-3: 민원 타임라인(inquiry_events) 신설 — 상태·배정 변경 append(docs/03 §4.4).
스키마(create_table)와 RLS·GRANT(op.execute)를 한 마이그레이션에 둔다
(RLS/role은 autogenerate 대상 아님 — 357f10ab881d 스타일 준수).

append-only: liviq_app에 SELECT·INSERT만 GRANT(UPDATE/DELETE 권한 없음, audit_logs 패턴).
inquiries에 UNIQUE(tenant_id, id)를 부여해 composite tenant FK로 cross-tenant 참조를 차단(§5).

Revision ID: c1a2b3d4e5f6
Revises: 357f10ab881d
Create Date: 2026-07-17 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1a2b3d4e5f6"
down_revision: str | None = "357f10ab881d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # inquiries composite FK 대상(§5) — 기존 행에 영향 없음(중복 (tenant_id, id) 불가).
    op.create_unique_constraint(
        "uq_inquiries_tenant_id_id", "inquiries", ["tenant_id", "id"]
    )

    op.create_table(
        "inquiry_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("inquiry_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_inquiry_events_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name="fk_inquiry_events_inquiry",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inquiry_events")),
    )
    op.create_index(
        "ix_inquiry_events_tenant_inquiry",
        "inquiry_events",
        ["tenant_id", "inquiry_id", "created_at"],
        unique=False,
    )

    # 표준 tenant 격리 + FORCE. append-only — SELECT·INSERT만 GRANT(§4.4).
    op.execute("ALTER TABLE inquiry_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE inquiry_events FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON inquiry_events FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    op.execute("GRANT SELECT, INSERT ON inquiry_events TO liviq_app")


def downgrade() -> None:
    # 정책·GRANT는 테이블과 함께 소멸.
    op.drop_index("ix_inquiry_events_tenant_inquiry", table_name="inquiry_events")
    op.drop_table("inquiry_events")
    op.drop_constraint("uq_inquiries_tenant_id_id", "inquiries", type_="unique")
