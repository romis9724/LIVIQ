"""시설 코드 부여 규칙 + DB 유일성·격리 (H14-2).

규칙은 순수 함수(런타임 부여와 마이그레이션 백필의 단일 출처)라 DB 없이 검증하고,
`(tenant_id, code)` UNIQUE는 실 PostgreSQL에서 확인한다 — 같은 코드가 다른 단지에
공존해야 하고(규칙 3 격리), 같은 단지 안에서는 거부돼야 한다.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from conftest import Seed
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from liviq_db.codes_seed import DEFAULT_CODE_GROUPS
from liviq_db.facility_systems import (
    FACILITY_SYSTEMS,
    facility_code_prefix,
    format_facility_code,
    next_facility_code,
)

_DB_ROOT = Path(__file__).resolve().parent.parent
# c5d6e7f8a9b0(facility_codes)의 down_revision — 왕복 대상 하한.
_FACILITY_CODES_PARENT = "b3c4d5e6f7a8"


# ── 부여 규칙(순수 함수) ─────────────────────────────────────────────────────


@pytest.mark.parametrize(("slug", "abbr"), [(s.slug, s.abbr) for s in FACILITY_SYSTEMS])
def test_prefix_uses_registered_system_abbreviation(slug: str, abbr: str) -> None:
    assert facility_code_prefix(slug, "401동") == f"{abbr}-401"


def test_prefix_falls_back_to_general_abbreviation_for_unknown_type() -> None:
    assert facility_code_prefix(None, "401동") == "GN-401"
    assert facility_code_prefix("", "401동") == "GN-401"
    assert facility_code_prefix("우주엘리베이터", "401동") == "GN-401"


def test_prefix_extracts_first_digit_run_from_location() -> None:
    assert facility_code_prefix("elevator", "401동") == "EL-401"
    assert facility_code_prefix("water", "지하1층 기계실") == "WT-1"
    assert facility_code_prefix("water", "101동 202호") == "WT-101"


def test_prefix_falls_back_to_common_when_location_has_no_digits() -> None:
    assert facility_code_prefix("security", None) == "SC-CMN"
    assert facility_code_prefix("security", "관리사무소") == "SC-CMN"


def test_format_pads_to_two_digits_and_grows_past_99() -> None:
    assert format_facility_code("EL-401", 1) == "EL-401-01"
    assert format_facility_code("EL-401", 99) == "EL-401-99"
    assert format_facility_code("EL-401", 100) == "EL-401-100"


def test_next_code_starts_at_one_and_increments_from_max() -> None:
    assert next_facility_code("EL-401", []) == "EL-401-01"
    assert next_facility_code("EL-401", ["EL-401-01", "EL-401-03"]) == "EL-401-04"


def test_next_code_ignores_other_prefixes_and_malformed_codes() -> None:
    existing = ["EL-402-09", "FR-401-07", "EL-401-XX", "EL-401", "EL-401-02"]
    assert next_facility_code("EL-401", existing) == "EL-401-03"


def test_next_code_does_not_reuse_deleted_sequence() -> None:
    """삭제된 시설의 코드도 조회에 포함해 넘기므로 연번이 재사용되지 않는다."""
    assert next_facility_code("EL-401", ["EL-401-01", "EL-401-02"]) == "EL-401-03"


# ── 코드 그룹 시드 ───────────────────────────────────────────────────────────


def test_facility_system_group_is_seeded_from_single_source() -> None:
    group = next(g for g in DEFAULT_CODE_GROUPS if g.group_key == "FACILITY_SYSTEM")
    assert [(c.code, c.label) for c in group.codes] == [(s.abbr, s.label) for s in FACILITY_SYSTEMS]


@pytest.mark.parametrize("group_key", ["PLAN_DEVICE_TYPE", "PLAN_ROOM"])
def test_plan_groups_are_seeded_with_code_equal_label(group_key: str) -> None:
    group = next(g for g in DEFAULT_CODE_GROUPS if g.group_key == group_key)
    assert len(group.codes) == 14
    assert all(c.code == c.label for c in group.codes)


# ── DB 유일성·격리 ───────────────────────────────────────────────────────────


async def _insert_facility(conn: AsyncConnection, tenant_id: uuid.UUID, code: str | None) -> None:
    await conn.execute(
        text(
            "INSERT INTO facilities(tenant_id, name, code, status) "
            "VALUES(:t, '승강기', :c, 'normal')"
        ).bindparams(t=tenant_id, c=code)
    )


async def test_same_code_coexists_across_tenants(owner_conn: AsyncConnection, seed: Seed) -> None:
    """단지가 다르면 같은 코드번호가 공존한다(코드는 단지 스코프 — 규칙 3)."""
    await _insert_facility(owner_conn, seed.a.tenant_id, "EL-401-01")
    await _insert_facility(owner_conn, seed.b.tenant_id, "EL-401-01")

    count = await owner_conn.scalar(
        text("SELECT count(*) FROM facilities WHERE code = 'EL-401-01'")
    )
    assert count == 2


async def test_duplicate_code_in_same_tenant_is_rejected(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    await _insert_facility(owner_conn, seed.a.tenant_id, "EL-401-01")
    with pytest.raises(IntegrityError):  # savepoint — 바깥 트랜잭션은 살려 롤백 픽스처를 지킨다
        async with owner_conn.begin_nested():
            await _insert_facility(owner_conn, seed.a.tenant_id, "EL-401-01")


async def test_null_codes_are_not_constrained(owner_conn: AsyncConnection, seed: Seed) -> None:
    """코드 없는 행(도입 이전 데이터)은 UNIQUE에 걸리지 않는다 — 컬럼 nullable 근거."""
    await _insert_facility(owner_conn, seed.a.tenant_id, None)
    await _insert_facility(owner_conn, seed.a.tenant_id, None)


# ── 마이그레이션 왕복 ────────────────────────────────────────────────────────


async def _code_column_exists(dsn: str) -> bool:
    engine = create_async_engine(dsn, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return bool(
                await conn.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'facilities' AND column_name = 'code'"
                    )
                )
            )
    finally:
        await engine.dispose()


def test_facility_code_migration_roundtrip(pg_dsn: str) -> None:
    """downgrade → upgrade 왕복. 다른 테스트가 쓰는 세션 DB라 반드시 head로 되돌린다.

    대상 리비전은 명시한다 — `-1`은 새 마이그레이션이 붙을 때마다 다른 것을 되돌린다.
    """
    os.environ["DATABASE_URL"] = pg_dsn
    cfg = Config()
    cfg.set_main_option("script_location", str(_DB_ROOT / "alembic"))
    try:
        command.downgrade(cfg, _FACILITY_CODES_PARENT)
        assert not asyncio.run(_code_column_exists(pg_dsn))
    finally:
        command.upgrade(cfg, "head")
    assert asyncio.run(_code_column_exists(pg_dsn))
