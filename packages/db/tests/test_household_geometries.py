"""household_geometries CRITICAL — 실 PostgreSQL에서 스키마 round-trip + tenant 격리(H9-1).

owner(superuser)로 시드 후 `set_context`로 런타임 role 전환해 검증한다(RLS는 owner가 우회하므로
격리 검증은 반드시 liviq_app role에서). 세대 3D 폴리곤은 렌더 전용 — 세대는 기존 명부 재사용.
"""

from __future__ import annotations

import uuid

import pytest
from conftest import Seed, set_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.integration


async def _insert_geometry(
    conn: AsyncConnection, tenant_id: object, household_id: object
) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO household_geometries"
            "(tenant_id, household_id, polygon_2d, polygon_3d, base_z, floor_height, "
            "area_m2, unit_type_label) "
            "VALUES(:t, :h, CAST(:p2 AS jsonb), CAST(:p3 AS jsonb), 2.992, 2.842, 84.7, '84M') "
            "RETURNING id"
        ).bindparams(
            t=tenant_id,
            h=household_id,
            p2="[[127.25, 36.48], [127.26, 36.49]]",
            p3="[[127.25, 36.48, 2.992], [127.26, 36.49, 2.992]]",
        )
    )
    value = result.scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


async def _count(conn: AsyncConnection) -> int:
    value = (await conn.execute(text("SELECT count(*) FROM household_geometries"))).scalar_one()
    return int(value)


async def test_geometry_round_trips(owner_conn: AsyncConnection, seed: Seed) -> None:
    """폴리곤(JSONB)·좌표(Numeric)가 마이그레이션 스키마를 왕복한다."""
    geometry_id = await _insert_geometry(owner_conn, seed.a.tenant_id, seed.a.household_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    row = (
        await owner_conn.execute(
            text(
                "SELECT polygon_2d, polygon_3d, base_z, floor_height, area_m2, unit_type_label "
                "FROM household_geometries WHERE id = :i"
            ).bindparams(i=geometry_id)
        )
    ).first()
    assert row is not None
    poly2, poly3, base_z, floor_height, area_m2, label = row
    assert poly2 == [[127.25, 36.48], [127.26, 36.49]]
    assert poly3 == [[127.25, 36.48, 2.992], [127.26, 36.49, 2.992]]
    assert float(base_z) == 2.992
    assert float(floor_height) == 2.842
    assert float(area_m2) == 84.7
    assert label == "84M"


async def test_geometry_tenant_isolation(owner_conn: AsyncConnection, seed: Seed) -> None:
    """A는 자기 geometry만 — B의 geometry는 안 보인다(격리 CRITICAL)."""
    await _insert_geometry(owner_conn, seed.a.tenant_id, seed.a.household_id)
    b_id = await _insert_geometry(owner_conn, seed.b.tenant_id, seed.b.household_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    assert await _count(owner_conn) == 1, "타 단지 geometry가 노출됨(격리 실패)"
    row = (
        await owner_conn.execute(
            text("SELECT id FROM household_geometries WHERE id = :i").bindparams(i=b_id)
        )
    ).first()
    assert row is None, "B 단지 geometry가 A 컨텍스트에서 조회됨(격리 실패)"


async def test_geometry_no_context_reads_zero(owner_conn: AsyncConnection, seed: Seed) -> None:
    """컨텍스트 미설정이면 geometry 0행(fail-closed)."""
    await _insert_geometry(owner_conn, seed.a.tenant_id, seed.a.household_id)
    await set_context(owner_conn, "liviq_app", tenant_id=None)

    assert await _count(owner_conn) == 0
