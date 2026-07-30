"""parking_layouts·parking_vehicles CRITICAL — 실 PostgreSQL 스키마 round-trip + tenant 격리(H9-5).

owner(superuser)로 시드 후 `set_context`로 런타임 role 전환해 검증한다(RLS는 owner가 우회하므로
격리 검증은 반드시 liviq_app role에서). 배치도는 단지당 1행(UNIQUE(tenant_id)), 차량은 세대당
다건 허용(UNIQUE 없음) + 세대 삭제 시 CASCADE.
"""

from __future__ import annotations

import json
import uuid

import pytest
from conftest import Seed, set_context
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.integration

_LAYOUT = {
    "viewBox": "0 0 3020 1082",
    "buildings": {"401동": {"outline": [[0, 0], [10, 0], [10, 10]], "cx": 5, "cy": 5}},
    "boxes": [{"label": "진입 램프 ⤵", "x": 100, "y": 1002, "w": 160, "h": 64}],
    "cores": [{"name": "401동", "x": 251, "y": 393.4, "w": 72, "h": 128}],
    "spots": [{"no": "001", "kind": "일반", "x": 100, "y": 162, "dir": "down"}],
}
_PLATE_BLOB = b"\x00\x01\x02nonce+ciphertext"  # bytea 왕복용 임의 blob


async def _insert_layout(conn: AsyncConnection, tenant_id: object) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO parking_layouts(tenant_id, layout) "
            "VALUES(:t, CAST(:payload AS jsonb)) RETURNING id"
        ).bindparams(t=tenant_id, payload=json.dumps(_LAYOUT))
    )
    value = result.scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


async def _insert_vehicle(
    conn: AsyncConnection,
    tenant_id: object,
    household_id: object,
    *,
    plate_enc: bytes = _PLATE_BLOB,
    model: str | None = "아이오닉5",
    is_ev: bool = True,
) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO parking_vehicles(tenant_id, household_id, plate_enc, model, is_ev) "
            "VALUES(:t, :h, :pe, :m, :ev) RETURNING id"
        ).bindparams(t=tenant_id, h=household_id, pe=plate_enc, m=model, ev=is_ev)
    )
    value = result.scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


async def _count(conn: AsyncConnection, table: str) -> int:
    value = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608
    return int(value)


async def _insert_occupancy_external(
    conn: AsyncConnection,
    tenant_id: object,
    *,
    spot_no: str = "001",
    plate_enc: bytes = _PLATE_BLOB,
    parked_hours: float = 3.5,
) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO parking_occupancy"
            "(tenant_id, spot_no, is_external, external_plate_enc, parked_hours) "
            "VALUES(:t, :s, true, :pe, :h) RETURNING id"
        ).bindparams(t=tenant_id, s=spot_no, pe=plate_enc, h=parked_hours)
    )
    value = result.scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


async def _insert_occupancy_resident(
    conn: AsyncConnection,
    tenant_id: object,
    vehicle_id: object,
    *,
    spot_no: str = "002",
    parked_hours: float = 6.0,
) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO parking_occupancy"
            "(tenant_id, spot_no, is_external, parking_vehicle_id, parked_hours) "
            "VALUES(:t, :s, false, :v, :h) RETURNING id"
        ).bindparams(t=tenant_id, s=spot_no, v=vehicle_id, h=parked_hours)
    )
    value = result.scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


# ── 배치도 ────────────────────────────────────────────────────────────────────


async def test_layout_round_trips(owner_conn: AsyncConnection, seed: Seed) -> None:
    """layout(JSONB)이 마이그레이션 스키마를 왕복한다(구조 보존)."""
    layout_id = await _insert_layout(owner_conn, seed.a.tenant_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    stored = (
        await owner_conn.execute(
            text("SELECT layout FROM parking_layouts WHERE id = :i").bindparams(i=layout_id)
        )
    ).scalar_one()
    assert stored == _LAYOUT


async def test_layout_unique_per_tenant(owner_conn: AsyncConnection, seed: Seed) -> None:
    """단지당 1행 — 같은 단지 두 번째 배치도는 UNIQUE(tenant_id) 위반."""
    await _insert_layout(owner_conn, seed.a.tenant_id)
    with pytest.raises(IntegrityError):
        await _insert_layout(owner_conn, seed.a.tenant_id)


async def test_layout_tenant_isolation(owner_conn: AsyncConnection, seed: Seed) -> None:
    """A는 자기 배치도만 — B의 배치도는 안 보인다(격리 CRITICAL)."""
    await _insert_layout(owner_conn, seed.a.tenant_id)
    b_id = await _insert_layout(owner_conn, seed.b.tenant_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    assert await _count(owner_conn, "parking_layouts") == 1, "타 단지 배치도가 노출됨(격리 실패)"
    row = (
        await owner_conn.execute(
            text("SELECT id FROM parking_layouts WHERE id = :i").bindparams(i=b_id)
        )
    ).first()
    assert row is None, "B 단지 배치도가 A 컨텍스트에서 조회됨(격리 실패)"


# ── 차량 ──────────────────────────────────────────────────────────────────────


async def test_vehicle_round_trips(owner_conn: AsyncConnection, seed: Seed) -> None:
    """plate_enc(bytea)·model·is_ev가 스키마를 왕복한다."""
    vehicle_id = await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    row = (
        await owner_conn.execute(
            text("SELECT plate_enc, model, is_ev FROM parking_vehicles WHERE id = :i").bindparams(
                i=vehicle_id
            )
        )
    ).first()
    assert row is not None
    plate_enc, model, is_ev = row
    assert bytes(plate_enc) == _PLATE_BLOB
    assert (model, is_ev) == ("아이오닉5", True)


async def test_vehicle_plate_enc_required(owner_conn: AsyncConnection, seed: Seed) -> None:
    """plate_enc는 NOT NULL — 차량번호 없는 행은 만들 수 없다."""
    with pytest.raises(IntegrityError):
        await owner_conn.execute(
            text("INSERT INTO parking_vehicles(tenant_id, household_id) VALUES(:t, :h)").bindparams(
                t=seed.a.tenant_id, h=seed.a.household_id
            )
        )


async def test_multiple_vehicles_per_household(owner_conn: AsyncConnection, seed: Seed) -> None:
    """세대당 다건 허용 — UNIQUE(tenant_id, household_id) 없음."""
    await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id, model="G80")
    await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id, model="아이오닉5")
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)
    assert await _count(owner_conn, "parking_vehicles") == 2


async def test_vehicle_tenant_isolation(owner_conn: AsyncConnection, seed: Seed) -> None:
    """A는 자기 차량만 — B의 차량은 안 보인다(격리 CRITICAL)."""
    await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id)
    b_id = await _insert_vehicle(owner_conn, seed.b.tenant_id, seed.b.household_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    assert await _count(owner_conn, "parking_vehicles") == 1, "타 단지 차량이 노출됨(격리 실패)"
    row = (
        await owner_conn.execute(
            text("SELECT id FROM parking_vehicles WHERE id = :i").bindparams(i=b_id)
        )
    ).first()
    assert row is None, "B 단지 차량이 A 컨텍스트에서 조회됨(격리 실패)"


async def test_no_context_reads_zero(owner_conn: AsyncConnection, seed: Seed) -> None:
    """컨텍스트 미설정이면 배치도·차량 0행(fail-closed)."""
    await _insert_layout(owner_conn, seed.a.tenant_id)
    await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id)
    await set_context(owner_conn, "liviq_app", tenant_id=None)

    assert await _count(owner_conn, "parking_layouts") == 0
    assert await _count(owner_conn, "parking_vehicles") == 0


async def test_vehicle_cascades_on_household_delete(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    """세대 삭제 시 차량도 함께 삭제(FK ondelete CASCADE)."""
    # 의존자 없는 새 세대에서 검증 — seed 세대는 user·inquiry가 부착돼 삭제가 막힌다.
    hid = (
        await owner_conn.execute(
            text(
                "INSERT INTO households(tenant_id, building_id, floor, unit_no, status) "
                "VALUES(:t, :b, 9, 901, 'active') RETURNING id"
            ).bindparams(t=seed.a.tenant_id, b=seed.a.building_id)
        )
    ).scalar_one()
    await _insert_vehicle(owner_conn, seed.a.tenant_id, hid)
    await owner_conn.execute(text("DELETE FROM households WHERE id = :h").bindparams(h=hid))
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)
    assert await _count(owner_conn, "parking_vehicles") == 0


# ── 점유 (parking_occupancy, H15-4) ────────────────────────────────────────────


async def test_occupancy_external_round_trips(owner_conn: AsyncConnection, seed: Seed) -> None:
    """외부차 점유 — is_external=true·external_plate_enc(bytea)·parked_hours 왕복."""
    occ_id = await _insert_occupancy_external(owner_conn, seed.a.tenant_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    row = (
        await owner_conn.execute(
            text(
                "SELECT spot_no, is_external, external_plate_enc, parking_vehicle_id, parked_hours "
                "FROM parking_occupancy WHERE id = :i"
            ).bindparams(i=occ_id)
        )
    ).first()
    assert row is not None
    spot_no, is_external, plate_enc, vehicle_id, parked_hours = row
    assert (spot_no, is_external) == ("001", True)
    assert bytes(plate_enc) == _PLATE_BLOB
    assert vehicle_id is None
    assert parked_hours == 3.5


async def test_occupancy_resident_round_trips(owner_conn: AsyncConnection, seed: Seed) -> None:
    """입주민 점유 — parking_vehicle_id composite FK·external_plate_enc NULL 왕복."""
    vehicle_id = await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id)
    occ_id = await _insert_occupancy_resident(owner_conn, seed.a.tenant_id, vehicle_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    row = (
        await owner_conn.execute(
            text(
                "SELECT is_external, parking_vehicle_id, external_plate_enc "
                "FROM parking_occupancy WHERE id = :i"
            ).bindparams(i=occ_id)
        )
    ).first()
    assert row is not None
    is_external, got_vehicle_id, plate_enc = row
    assert is_external is False
    assert got_vehicle_id == vehicle_id
    assert plate_enc is None


async def test_occupancy_check_rejects_resident_without_vehicle(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    """무결성 CHECK — is_external=false인데 parking_vehicle_id 없으면 거부."""
    with pytest.raises(IntegrityError):
        await owner_conn.execute(
            text(
                "INSERT INTO parking_occupancy(tenant_id, spot_no, is_external) "
                "VALUES(:t, '003', false)"
            ).bindparams(t=seed.a.tenant_id)
        )


async def test_occupancy_check_rejects_external_with_vehicle(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    """무결성 CHECK — is_external=true인데 external_plate_enc 없으면 거부."""
    with pytest.raises(IntegrityError):
        await owner_conn.execute(
            text(
                "INSERT INTO parking_occupancy(tenant_id, spot_no, is_external) "
                "VALUES(:t, '004', true)"
            ).bindparams(t=seed.a.tenant_id)
        )


async def test_occupancy_unique_spot_per_tenant(owner_conn: AsyncConnection, seed: Seed) -> None:
    """면당 1행 — 같은 단지 같은 spot_no 두 번째 점유는 UNIQUE(tenant_id, spot_no) 위반."""
    await _insert_occupancy_external(owner_conn, seed.a.tenant_id, spot_no="005")
    with pytest.raises(IntegrityError):
        await _insert_occupancy_external(owner_conn, seed.a.tenant_id, spot_no="005")


async def test_occupancy_tenant_isolation(owner_conn: AsyncConnection, seed: Seed) -> None:
    """A는 자기 점유만 — B의 점유는 안 보인다(격리 CRITICAL)."""
    await _insert_occupancy_external(owner_conn, seed.a.tenant_id)
    b_id = await _insert_occupancy_external(owner_conn, seed.b.tenant_id)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    assert await _count(owner_conn, "parking_occupancy") == 1, "타 단지 점유가 노출됨(격리 실패)"
    row = (
        await owner_conn.execute(
            text("SELECT id FROM parking_occupancy WHERE id = :i").bindparams(i=b_id)
        )
    ).first()
    assert row is None, "B 단지 점유가 A 컨텍스트에서 조회됨(격리 실패)"
