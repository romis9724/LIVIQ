"""공지 분류 코드 확충 — NOTICE_CATEGORY 누락 코드만 기존 단지에 보충 (공지 데모 시드 86건)

공지 데모 데이터(apps/api/scripts/data/notices_demo.py)가 쓰는 분류 라벨이 9종 늘었다
(생활안전·안전점검·생활안내·관리비·환경정비·주차·재난안전·조경관리·관리정보). 코드가 없으면
시드가 category_code_id=NULL로 들어가므로 기존 단지에 미리 보충한다.

그룹(NOTICE_CATEGORY)은 이미 존재하므로 **만들지 않는다** — 그룹 내 기존 code와의 차집합만
INSERT하고 sort_order는 현재 max+1부터 이어붙인다(기존 코드의 정렬 불변). 값은
`liviq_db.codes_seed.DEFAULT_CODE_GROUPS` 단일 출처에서 뽑는다.

신규 DB(tenants 0개)는 no-op — 단지 생성 API가 시드한다(seed_default_codes).
마이그레이션은 owner 롤로 실행되므로 RLS를 우회한다(c4a7e2f1b9d3와 동일 전제, docs/03 §5.1).

Revision ID: d8e9f0a1b2c3
Revises: c6d7e8f9a0b1
Create Date: 2026-08-01 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from liviq_db.codes_seed import DEFAULT_CODE_GROUPS

revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GROUP_KEY = "NOTICE_CATEGORY"
# 시스템 테넌트(SYS_ADMIN 소속, 단지 아님) — apps/api/app/config.SYSTEM_TENANT_ID와 동일 상수.
_SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"
# 이 마이그레이션이 추가하는 코드는 seed 목록의 이 인덱스부터 — 앞 6종은 초기 스키마·H8-6이 심었다.
_ADDED_FROM = 6


def _seed_codes() -> tuple[tuple[str, str], ...]:
    """DEFAULT_CODE_GROUPS(단일 출처)에서 NOTICE_CATEGORY (code, label) 목록 추출."""
    group = next(g for g in DEFAULT_CODE_GROUPS if g.group_key == _GROUP_KEY)
    return tuple((c.code, c.label) for c in group.codes)


def _group_ids(conn: sa.Connection) -> list[tuple[str, str]]:
    """기존 단지의 (tenant_id, NOTICE_CATEGORY group_id) 목록(시스템 테넌트 제외)."""
    rows = conn.execute(
        # code_groups.tenant_id는 tenants FK라 별도 조인 불필요(단지 0개면 결과 0행 = no-op).
        sa.text("SELECT tenant_id, id FROM code_groups WHERE group_key = :k AND tenant_id <> :sys"),
        {"k": _GROUP_KEY, "sys": _SYSTEM_TENANT_ID},
    )
    return [(row[0], row[1]) for row in rows]


def upgrade() -> None:
    conn = op.get_bind()
    codes = _seed_codes()
    for tenant_id, group_id in _group_ids(conn):
        existing = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT code FROM codes WHERE tenant_id = :t AND group_id = :g"),
                {"t": tenant_id, "g": group_id},
            )
        }
        next_order: int = conn.execute(
            sa.text(
                "SELECT coalesce(max(sort_order), -1) + 1 FROM codes "
                "WHERE tenant_id = :t AND group_id = :g"
            ),
            {"t": tenant_id, "g": group_id},
        ).scalar_one()
        for order, (code, label) in enumerate(
            [c for c in codes if c[0] not in existing], start=next_order
        ):
            conn.execute(
                sa.text(
                    "INSERT INTO codes (tenant_id, group_id, code, label, sort_order) "
                    "VALUES (:t, :g, :c, :l, :o)"
                ),
                {"t": tenant_id, "g": group_id, "c": code, "l": label, "o": order},
            )


def downgrade() -> None:
    # 이 마이그레이션이 추가한 9종만 삭제. notices.category_code_id가 참조 중이면
    # FK RESTRICT로 DELETE가 실패하므로 미참조 코드만 지운다(공지 데모 시드 후 downgrade 가능).
    conn = op.get_bind()
    added = [code for code, _ in _seed_codes()[_ADDED_FROM:]]
    conn.execute(
        sa.text(
            "DELETE FROM codes c USING code_groups g "
            "WHERE g.id = c.group_id AND g.tenant_id = c.tenant_id "
            "AND g.group_key = :k AND c.tenant_id <> :sys AND c.code IN :codes "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM notices n "
            "  WHERE n.tenant_id = c.tenant_id AND n.category_code_id = c.id"
            ")"
        ).bindparams(
            sa.bindparam("k", _GROUP_KEY),
            # type_ 없이 str을 넘기면 asyncpg가 VARCHAR로 캐스팅해 `uuid <> varchar`로 깨진다.
            sa.bindparam("sys", _SYSTEM_TENANT_ID, type_=sa.UUID),
            sa.bindparam("codes", added, expanding=True),
        )
    )
