"""facilities.code — 시설 코드번호 + 시설·평면도 공통 코드 그룹 (H14-2)

시설 코드는 `{계통약어}-{위치약어}-{연번}`(A안, 예 `EL-401-01`)이며 서버가 부여한다.
기존 행은 liviq_db.facility_systems의 순수 규칙으로 백필하고(생성순 연번, 소프트 삭제된
행도 연번을 차지 — 재사용 금지), 이후 (tenant_id, code) UNIQUE로 중복을 DB가 막는다.
컬럼은 nullable 유지 — NULL은 UNIQUE에서 자유롭고, 신규 행은 API가 항상 부여한다.

함께 기존 단지에 코드 그룹 3종(FACILITY_SYSTEM·PLAN_DEVICE_TYPE·PLAN_ROOM)을 시드한다
(ADR-0017 전례: c4a7e2f1b9d3). 신규 DB는 tenants가 비어 no-op — 단지 생성 API가 시드한다.

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-07-27 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from liviq_db.codes_seed import DEFAULT_CODE_GROUPS
from liviq_db.facility_systems import facility_code_prefix, format_facility_code

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "uq_facilities_tenant_code"
_GROUP_KEYS = ("FACILITY_SYSTEM", "PLAN_DEVICE_TYPE", "PLAN_ROOM")
# 시스템 테넌트(SYS_ADMIN 소속, 단지 아님) — apps/api/app/config.SYSTEM_TENANT_ID와 동일 상수.
_SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def _backfill_codes() -> None:
    """기존 시설에 코드 부여 — 런타임과 같은 순수 규칙을 재사용한다(규칙 중복 정의 금지)."""
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, tenant_id, type, location FROM facilities "
            "ORDER BY tenant_id, created_at, id"
        )
    ).all()
    last_seq: dict[tuple[str, str], int] = {}
    for row in rows:
        prefix = facility_code_prefix(row.type, row.location)
        key = (str(row.tenant_id), prefix)
        seq = last_seq[key] = last_seq.get(key, 0) + 1
        conn.execute(
            sa.text("UPDATE facilities SET code = :c WHERE id = :i"),
            {"c": format_facility_code(prefix, seq), "i": row.id},
        )


def _seed_existing_tenants() -> None:
    """기존 단지에 코드 그룹 3종 시드(시스템 테넌트 제외). 마이그레이션은 owner로 실행."""
    conn = op.get_bind()
    groups = [g for g in DEFAULT_CODE_GROUPS if g.group_key in _GROUP_KEYS]
    tenant_ids = [
        row[0]
        for row in conn.execute(
            sa.text("SELECT id FROM tenants WHERE id <> :sys"), {"sys": _SYSTEM_TENANT_ID}
        )
    ]
    for tenant_id in tenant_ids:
        for group in groups:
            group_id = conn.execute(
                sa.text(
                    "INSERT INTO code_groups (tenant_id, group_key, name, is_system) "
                    "VALUES (:t, :k, :n, true) "
                    "ON CONFLICT (tenant_id, group_key) DO NOTHING RETURNING id"
                ),
                {"t": tenant_id, "k": group.group_key, "n": group.name},
            ).scalar()
            if group_id is None:  # 이미 있는 단지(재적용) — 코드 행은 건드리지 않는다
                continue
            for order, code in enumerate(group.codes):
                conn.execute(
                    sa.text(
                        "INSERT INTO codes (tenant_id, group_id, code, label, sort_order) "
                        "VALUES (:t, :g, :c, :l, :o)"
                    ),
                    {"t": tenant_id, "g": group_id, "c": code.code, "l": code.label, "o": order},
                )


def upgrade() -> None:
    op.add_column("facilities", sa.Column("code", sa.String(), nullable=True))
    _backfill_codes()
    op.create_unique_constraint(_CONSTRAINT, "facilities", ["tenant_id", "code"])
    _seed_existing_tenants()


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "facilities", type_="unique")
    op.drop_column("facilities", "code")
    # 코드 행은 그룹 CASCADE로 함께 소멸.
    op.execute(
        "DELETE FROM code_groups WHERE group_key IN "
        f"({', '.join(repr(k) for k in _GROUP_KEYS)}) AND tenant_id <> '{_SYSTEM_TENANT_ID}'"
    )
