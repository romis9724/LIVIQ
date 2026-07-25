"""parking_assignments CRITICAL — 실 PostgreSQL에서 스키마 round-trip + tenant 격리(H9-5).

owner(superuser)로 시드 후 `set_context`로 런타임 role 전환해 검증한다(RLS는 owner가 우회하므로
격리 검증은 반드시 liviq_app role에서). 세대당 다건 배정 허용(UNIQUE 없음)도 함께 본다.
"""

from __future__ import annotations

import uuid

import pytest
from conftest import Seed, set_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.integration

_PLATE_BLOB = b"\x00\x01\x02nonce+ciphertext"  # bytea 왕복용 임의 blob


async def _insert_assignment(
    conn: AsyncConnection,
    tenant_id: object,
    household_id: object,
    *,
    location_code: str | None = "B2-A-12",
    plate_enc: bytes | None = _PLATE_BLOB,
) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO parking_assignments(tenant_id, household_id, location_code, plate_enc) "
            "VALUES(:t, :h, :lc, :pe) RETURNING id"
        ).bindparams(t=tenant_id, h=household_id, lc=location_code, pe=plate_enc)
    )
    value = result.scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


async def _count(conn: AsyncConnection) -> int:
    value = (await conn.execute(text("SELECT count(*) FROM parking_assignments"))).scalar_one()
    return int(value)


async def test_assignment_round_trips(owner_conn: AsyncConnection, seed: Seed) -> None:
    """location_code(String)·plate_enc(bytea)가 마이그레이션 스키마를 왕복한다."""
    assignment_id = await _insert_assignment(owner_conn, seed.a.tenant_id, seed.a.household_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    row = (
        await owner_conn.execute(
            text(
                "SELECT location_code, plate_enc FROM parking_assignments WHERE id = :i"
            ).bindparams(i=assignment_id)
        )
    ).first()
    assert row is not None
    location_code, plate_enc = row
    assert location_code == "B2-A-12"
    assert bytes(plate_enc) == _PLATE_BLOB


async def test_assignment_allows_nullable_columns(owner_conn: AsyncConnection, seed: Seed) -> None:
    """location_code·plate_enc는 선택 — 둘 다 NULL인 배정도 허용."""
    assignment_id = await _insert_assignment(
        owner_conn, seed.a.tenant_id, seed.a.household_id, location_code=None, plate_enc=None
    )
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)
    row = (
        await owner_conn.execute(
            text(
                "SELECT location_code, plate_enc FROM parking_assignments WHERE id = :i"
            ).bindparams(i=assignment_id)
        )
    ).first()
    assert row == (None, None)


async def test_multiple_assignments_per_household(owner_conn: AsyncConnection, seed: Seed) -> None:
    """세대당 다건 허용 — UNIQUE(tenant_id, household_id) 없음."""
    await _insert_assignment(
        owner_conn, seed.a.tenant_id, seed.a.household_id, location_code="B2-A-12"
    )
    await _insert_assignment(
        owner_conn, seed.a.tenant_id, seed.a.household_id, location_code="B2-A-13"
    )
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)
    assert await _count(owner_conn) == 2


async def test_assignment_tenant_isolation(owner_conn: AsyncConnection, seed: Seed) -> None:
    """A는 자기 배정만 — B의 배정은 안 보인다(격리 CRITICAL)."""
    await _insert_assignment(owner_conn, seed.a.tenant_id, seed.a.household_id)
    b_id = await _insert_assignment(owner_conn, seed.b.tenant_id, seed.b.household_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    assert await _count(owner_conn) == 1, "타 단지 주차 배정이 노출됨(격리 실패)"
    row = (
        await owner_conn.execute(
            text("SELECT id FROM parking_assignments WHERE id = :i").bindparams(i=b_id)
        )
    ).first()
    assert row is None, "B 단지 주차 배정이 A 컨텍스트에서 조회됨(격리 실패)"


async def test_assignment_no_context_reads_zero(owner_conn: AsyncConnection, seed: Seed) -> None:
    """컨텍스트 미설정이면 배정 0행(fail-closed)."""
    await _insert_assignment(owner_conn, seed.a.tenant_id, seed.a.household_id)
    await set_context(owner_conn, "liviq_app", tenant_id=None)

    assert await _count(owner_conn) == 0


async def test_assignment_cascades_on_household_delete(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    """세대 삭제 시 배정도 함께 삭제(FK ondelete CASCADE)."""
    # 의존자 없는 새 세대에서 검증 — seed 세대는 user·inquiry가 부착돼 삭제가 막힌다.
    hid = (
        await owner_conn.execute(
            text(
                "INSERT INTO households(tenant_id, building_id, floor, unit_no, status) "
                "VALUES(:t, :b, 9, 901, 'active') RETURNING id"
            ).bindparams(t=seed.a.tenant_id, b=seed.a.building_id)
        )
    ).scalar_one()
    await _insert_assignment(owner_conn, seed.a.tenant_id, hid)
    await owner_conn.execute(text("DELETE FROM households WHERE id = :h").bindparams(h=hid))
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)
    assert await _count(owner_conn) == 0
