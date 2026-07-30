"""incidents.caused_by_incident_id — 다단계 인과 self-FK (GraphRAG G1a, SEED-PLAN §1)

incident 간 인과 연쇄(원인→결과)를 실제 엣지로 만들기 위한 스키마 기반이다.
자기참조 nullable FK이며 tenant 스코프다 — `(tenant_id, caused_by_incident_id)`가
`incidents(tenant_id, id)`를 참조하는 composite FK라, 다른 단지의 incident를 원인으로
가리키는 행을 DB가 거부한다(규칙 3 tenant 격리). composite FK 대상이 되려면 부모 쪽에
`UNIQUE(tenant_id, id)`가 필요해 함께 추가한다(inquiries.facility_id 전례와 동일 패턴,
a2b3c4d5e6f7).

순수 컬럼·제약 추가라 incidents의 기존 tenant RLS 정책(tenant_isolation FOR ALL,
eaf86de665b0)·GRANT는 그대로다 — 격리는 RLS(행 가시성) + composite FK(참조 무결성)
이중으로 성립한다. 컬럼은 nullable 유지: 선행 원인 없는 단독 장애가 다수고, NULL이면
composite FK는 MATCH SIMPLE 규칙으로 미검증이다.

Revision ID: a3b4c5d6e7f8
Revises: f1a2b3c4d5e6
Create Date: 2026-07-30 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIQUE = "uq_incidents_tenant_id_id"
_FK = "fk_incidents_caused_by"
_INDEX = "ix_incidents_tenant_caused_by"


def upgrade() -> None:
    op.create_unique_constraint(_UNIQUE, "incidents", ["tenant_id", "id"])
    op.add_column("incidents", sa.Column("caused_by_incident_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        _FK,
        "incidents",
        "incidents",
        ["tenant_id", "caused_by_incident_id"],
        ["tenant_id", "id"],
    )
    op.create_index(_INDEX, "incidents", ["tenant_id", "caused_by_incident_id"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="incidents")
    op.drop_constraint(_FK, "incidents", type_="foreignkey")
    op.drop_column("incidents", "caused_by_incident_id")
    op.drop_constraint(_UNIQUE, "incidents", type_="unique")
