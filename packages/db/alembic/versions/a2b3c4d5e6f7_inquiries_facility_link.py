"""inquiries.facility_id — 민원-시설 정식 연결 (H13-2, ADR-0022 결정 3)

담당자 승인으로만 채워지는 nullable FK다(LLM 추천은 후보 제시까지 — 규칙 8).
(tenant_id, facility_id) → facilities(tenant_id, id) composite FK라 타 단지 설비 참조는
DB가 거부한다(docs/03 §5). 순수 컬럼 추가라 inquiries의 기존 tenant RLS 정책·GRANT는 그대로다
(정책은 FOR ALL tenant_id 기준, GRANT는 테이블 단위).

Revision ID: a2b3c4d5e6f7
Revises: f1a9c3e5b7d2
Create Date: 2026-07-27 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f1a9c3e5b7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("inquiries", sa.Column("facility_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_inquiries_facility",
        "inquiries",
        "facilities",
        ["tenant_id", "facility_id"],
        ["tenant_id", "id"],
    )
    op.create_index("ix_inquiries_tenant_facility", "inquiries", ["tenant_id", "facility_id"])


def downgrade() -> None:
    op.drop_index("ix_inquiries_tenant_facility", table_name="inquiries")
    op.drop_constraint("fk_inquiries_facility", "inquiries", type_="foreignkey")
    op.drop_column("inquiries", "facility_id")
