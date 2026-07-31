"""parking_layouts·parking_vehicles CRITICAL — 실 PostgreSQL 스키마 round-trip + tenant 격리(H9-5).

owner(superuser)로 시드 후 `set_context`로 런타임 role 전환해 검증한다(RLS는 owner가 우회하므로
격리 검증은 반드시 liviq_app role에서). 배치도는 단지당 1행(UNIQUE(tenant_id)), 차량은 세대당
다건 허용(UNIQUE 없음) + 세대 삭제 시 CASCADE. 점유(H16)는 spot_no·entry_at 왕복 + 부분
유니크(한 면 한 대) + 외부 차량(household_id NULL)까지.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from conftest import Seed, set_context
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

_DB_ROOT = Path(__file__).resolve().parent.parent
# b4c5d6e7f8a9(spot_no·entry_at)의 down_revision — 왕복 대상 하한.
_OCCUPANCY_PARENT = "a3b4c5d6e7f8"

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
    spot_no: str | None = None,
    entry_at: object = None,
) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO parking_vehicles"
            "(tenant_id, household_id, plate_enc, model, is_ev, spot_no, entry_at) "
            "VALUES(:t, :h, :pe, :m, :ev, :sn, :ea) RETURNING id"
        ).bindparams(
            t=tenant_id,
            h=household_id,
            pe=plate_enc,
            m=model,
            ev=is_ev,
            sn=spot_no,
            ea=entry_at,
        )
    )
    value = result.scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


async def _count(conn: AsyncConnection, table: str) -> int:
    value = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608
    return int(value)


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


async def test_vehicle_occupancy_round_trips(owner_conn: AsyncConnection, seed: Seed) -> None:
    """spot_no·entry_at(점유 상태)이 스키마를 왕복한다(H16 — 점유의 단일 출처는 DB)."""
    entry_at = datetime.datetime(2026, 7, 31, 3, 20, tzinfo=datetime.UTC)
    vehicle_id = await _insert_vehicle(
        owner_conn, seed.a.tenant_id, seed.a.household_id, spot_no="042", entry_at=entry_at
    )
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    row = (
        await owner_conn.execute(
            text("SELECT spot_no, entry_at FROM parking_vehicles WHERE id = :i").bindparams(
                i=vehicle_id
            )
        )
    ).first()
    assert row is not None
    assert row[0] == "042"
    assert row[1] == entry_at


async def test_external_vehicle_without_household(owner_conn: AsyncConnection, seed: Seed) -> None:
    """household_id NULL = 외부 차량 — 명부에 없는 차량도 점유를 가질 수 있다(H16)."""
    vehicle_id = await _insert_vehicle(
        owner_conn, seed.a.tenant_id, None, model=None, spot_no="777"
    )
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    row = (
        await owner_conn.execute(
            text("SELECT household_id, spot_no FROM parking_vehicles WHERE id = :i").bindparams(
                i=vehicle_id
            )
        )
    ).first()
    assert row == (None, "777")


async def test_spot_unique_per_tenant(owner_conn: AsyncConnection, seed: Seed) -> None:
    """한 면에 두 대 금지 — 같은 단지의 같은 spot_no는 부분 유니크 위반(H16)."""
    await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id, spot_no="042")
    with pytest.raises(IntegrityError):
        await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id, spot_no="042")


async def test_same_spot_no_across_tenants(owner_conn: AsyncConnection, seed: Seed) -> None:
    """유니크는 단지 스코프 — 다른 단지의 같은 면 번호는 허용."""
    await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id, spot_no="042")
    await _insert_vehicle(owner_conn, seed.b.tenant_id, seed.b.household_id, spot_no="042")
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)
    assert await _count(owner_conn, "parking_vehicles") == 1


async def test_multiple_unparked_vehicles(owner_conn: AsyncConnection, seed: Seed) -> None:
    """미주차(spot_no NULL)는 여러 대 허용 — 부분 유니크가 NULL을 안 건다(H16)."""
    await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id, model="G80")
    await _insert_vehicle(owner_conn, seed.a.tenant_id, seed.a.household_id, model="쏘나타")
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)
    assert await _count(owner_conn, "parking_vehicles") == 2


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


# ── 마이그레이션 왕복 (H16) ───────────────────────────────────────────────────


async def _occupancy_columns(dsn: str) -> int:
    engine = create_async_engine(dsn, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return int(
                await conn.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'parking_vehicles' "
                        "AND column_name IN ('spot_no', 'entry_at')"
                    )
                )
                or 0
            )
    finally:
        await engine.dispose()


def test_occupancy_migration_roundtrip(pg_dsn: str) -> None:
    """downgrade → upgrade 왕복(외부 차량 행 정리 포함). 세션 공용 DB라 반드시 head로 되돌린다."""
    os.environ["DATABASE_URL"] = pg_dsn
    cfg = Config()
    cfg.set_main_option("script_location", str(_DB_ROOT / "alembic"))
    try:
        command.downgrade(cfg, _OCCUPANCY_PARENT)
        assert asyncio.run(_occupancy_columns(pg_dsn)) == 0
    finally:
        command.upgrade(cfg, "head")
    assert asyncio.run(_occupancy_columns(pg_dsn)) == 2
