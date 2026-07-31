"""seed_parking `_replace_occupancy` 통합 — 실 PG (H15-4, ADR-0023).

배정 결과가 parking_occupancy 행으로 적재되는지, CHECK/UNIQUE·외부차 번호판 암호화(규칙 2)·
멱등 재실행을 실 DB로 본다. 순수 배정 로직은 packages/ai-core test_parking_geometry가 담당.
"""

from __future__ import annotations

import base64
import sys
import uuid
from pathlib import Path

import pytest_asyncio
from app.pii import PiiCrypto
from conftest import TENANT_ID, seed_tenant
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import ParkingOccupancy, ParkingVehicle

# scripts/는 패키지가 아니라 경로에 없다 — 시더 모듈을 직접 임포트한다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import seed_parking  # noqa: E402

_KEK = base64.b64encode(b"0" * 32).decode()
# 코어 "101동"(seed_tenant의 building name="101") 근처 일반 면 여러 개 — 배정 여유 확보.
_LAYOUT = {
    "viewBox": "0 0 3020 1082",
    "buildings": {},
    "boxes": [],
    "cores": [{"name": "101동", "x": 251, "y": 393.4, "w": 72, "h": 128}],
    "spots": [
        {"no": f"{i:03d}", "kind": "일반", "x": 100 + i * 34, "y": 162} for i in range(1, 21)
    ],
}


async def _add_vehicle(
    session: AsyncSession, household_id: uuid.UUID, *, is_ev: bool = False
) -> uuid.UUID:
    crypto = PiiCrypto(_KEK)
    dek = await crypto.get_dek(session, TENANT_ID)
    veh = ParkingVehicle(
        tenant_id=TENANT_ID,
        household_id=household_id,
        plate_enc=crypto.encrypt(dek, "12가3456"),
        model=None,
        is_ev=is_ev,
    )
    session.add(veh)
    await session.flush()
    return veh.id


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> tuple[AsyncSession, dict]:
    mapping = await seed_tenant(db_session)
    return db_session, mapping


async def test_occupancy_persists_resident_and_external(seeded: tuple) -> None:
    session, mapping = seeded
    vid = await _add_vehicle(session, mapping[(3, 301)])
    crypto = PiiCrypto(_KEK)

    resident, external, empty = await seed_parking._replace_occupancy(
        session, crypto, TENANT_ID, _LAYOUT
    )

    # 입주민 1대 + 외부차 기본 8대 배정, 면 20 − 9 = 11 빈 면.
    assert resident == 1
    assert external == 8
    assert empty == len(_LAYOUT["spots"]) - (resident + external)

    rows = (
        (
            await session.execute(
                select(ParkingOccupancy).where(ParkingOccupancy.tenant_id == TENANT_ID)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == resident + external

    res_rows = [r for r in rows if not r.is_external]
    ext_rows = [r for r in rows if r.is_external]
    # 입주민 행: 차량 FK 채움·번호판 암호문 없음(CHECK).
    assert len(res_rows) == 1
    assert res_rows[0].parking_vehicle_id == vid
    assert res_rows[0].external_plate_enc is None
    # 외부 행: 차량 FK 없음·번호판 암호문 채움(CHECK) — 평문은 저장 금지(규칙 2).
    assert len(ext_rows) == 8
    for r in ext_rows:
        assert r.parking_vehicle_id is None
        assert isinstance(r.external_plate_enc, bytes)
        plate = crypto.decrypt(await crypto.get_dek(session, TENANT_ID), r.external_plate_enc)
        assert plate  # 복호 성공(번호판 왕복)
        assert plate.encode("utf-8") not in r.external_plate_enc  # 평문 저장 안 함


async def test_occupancy_spot_no_unique(seeded: tuple) -> None:
    session, mapping = seeded
    await _add_vehicle(session, mapping[(3, 301)])
    await seed_parking._replace_occupancy(session, PiiCrypto(_KEK), TENANT_ID, _LAYOUT)
    total = await session.scalar(
        select(func.count())
        .select_from(ParkingOccupancy)
        .where(ParkingOccupancy.tenant_id == TENANT_ID)
    )
    distinct = await session.scalar(
        select(func.count(func.distinct(ParkingOccupancy.spot_no))).where(
            ParkingOccupancy.tenant_id == TENANT_ID
        )
    )
    assert total == distinct  # 면당 1행(UNIQUE(tenant_id, spot_no))


async def test_occupancy_idempotent_rerun(seeded: tuple) -> None:
    session, mapping = seeded
    await _add_vehicle(session, mapping[(3, 301)])
    crypto = PiiCrypto(_KEK)

    first = await seed_parking._replace_occupancy(session, crypto, TENANT_ID, _LAYOUT)
    count1 = await session.scalar(
        select(func.count())
        .select_from(ParkingOccupancy)
        .where(ParkingOccupancy.tenant_id == TENANT_ID)
    )
    second = await seed_parking._replace_occupancy(session, crypto, TENANT_ID, _LAYOUT)
    count2 = await session.scalar(
        select(func.count())
        .select_from(ParkingOccupancy)
        .where(ParkingOccupancy.tenant_id == TENANT_ID)
    )
    # delete-then-insert 전량 교체 — 재실행해도 개수·요약이 늘지 않는다.
    assert count1 == count2
    assert first == second
