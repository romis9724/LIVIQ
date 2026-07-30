"""seed_parking.py — 지하주차장 배치도·입주민 차량·면 점유 시드 (H9-5, H15-4/ADR-0023).

프로토타입 배치도(442면)와 입주민 차량(348대)을 DB에 적재하고, 결정적 배정으로 면 점유
(parking_occupancy, 점유의 단일 사실 원천)를 계산해 적재한다. 배치도는 단지당 1행,
차량은 명부(households) 매칭분만 — 셋 다 delete-then-insert 전량 교체(단일 트랜잭션)라
재실행해도 개수가 늘지 않는다. 차량번호·외부차 번호판은 봉투 암호화해 암호문만 저장한다(규칙 2).

입력은 `scripts/data/`의 추출물:
  - parking_layout.json   viewBox·buildings·boxes·cores·spots (렌더 페이로드 그대로)
  - parking_vehicles.json [{"plate","dong","ho","model","ev"}]

차량 dong("401동")·ho("1502호")를 명부 (buildings.name, households.unit_no)에 매칭한다
(seed_households_xlsx·twin과 동일 정규화). 미매칭은 스킵하고 리포트에 표본을 남긴다.

실행(DATABASE_URL·PII_MASTER_KEY는 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync python scripts/seed_parking.py [--tenant-id <uuid>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from app.pii import PiiCrypto, get_pii_crypto
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.parking import Core, Occupancy, Spot, VehicleRef, assign_occupancy
from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import (
    Building,
    Household,
    ParkingLayout,
    ParkingOccupancy,
    ParkingVehicle,
    Tenant,
)

# 파일럿 단지(첫마을 4단지 푸르지오) — dev 시드·seed_demo와 동일한 tenant.
DEFAULT_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

DATA_DIR = Path(__file__).resolve().parent / "data"
LAYOUT_FILE = DATA_DIR / "parking_layout.json"
VEHICLES_FILE = DATA_DIR / "parking_vehicles.json"

MAX_UNMATCHED_SAMPLES = 20  # 리포트에 담을 미매칭 차량 표본 상한
_LAYOUT_KEYS = ("viewBox", "buildings", "boxes", "cores", "spots")


def _load_layout() -> dict[str, Any]:
    """배치도 JSON 로드 — 최소 키만 확인하고 내용은 해석하지 않는다(렌더 페이로드)."""
    payload = json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"배치도 JSON은 객체여야 합니다: {LAYOUT_FILE}")
    missing = [key for key in _LAYOUT_KEYS if key not in payload]
    if missing:
        raise SystemExit(f"배치도 JSON에 키가 없습니다: {', '.join(missing)}")
    return payload


def _load_vehicles() -> list[dict[str, Any]]:
    """차량 JSON 로드 — plate·dong·ho 필수(없는 행은 적재 불가라 즉시 중단)."""
    payload = json.loads(VEHICLES_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise SystemExit(f"차량 JSON은 비어있지 않은 배열이어야 합니다: {VEHICLES_FILE}")
    for row in payload:
        if not all(row.get(key) for key in ("plate", "dong", "ho")):
            raise SystemExit(f"차량 행에 plate·dong·ho가 필요합니다: {row}")
    return payload


def _building_name(dong: str) -> str:
    """dong "401동" → buildings.name "401" (seed_households_xlsx·twin과 동일 정규화)."""
    return str(dong).replace("동", "").strip()


def _unit_no(ho: str) -> int | None:
    """ho "1502호" → households.unit_no 1502. 숫자가 아니면 None(미매칭 처리)."""
    digits = str(ho).replace("호", "").strip()
    return int(digits) if digits.isdigit() else None


async def _household_index(
    session: AsyncSession, tenant_id: uuid.UUID
) -> dict[tuple[str, int], uuid.UUID]:
    """(동 이름, 호) → household_id 색인 — 차량 매칭용."""
    rows = await session.execute(
        select(Building.name, Household.unit_no, Household.id)
        .join(Building, Building.id == Household.building_id)
        .where(Household.tenant_id == tenant_id)
    )
    return {(name, unit_no): hid for name, unit_no, hid in rows}


async def _replace_layout(
    session: AsyncSession, tenant_id: uuid.UUID, layout: dict[str, Any]
) -> None:
    """배치도 전량 교체 — 단지당 1행(UNIQUE(tenant_id))."""
    await session.execute(delete(ParkingLayout).where(ParkingLayout.tenant_id == tenant_id))
    session.add(ParkingLayout(tenant_id=tenant_id, layout=layout))
    await session.flush()


async def _replace_vehicles(
    session: AsyncSession,
    crypto: PiiCrypto,
    tenant_id: uuid.UUID,
    vehicles: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """차량 전량 교체 — 명부 매칭분만 적재. (매칭 수, 미매칭 표본) 반환."""
    index = await _household_index(session, tenant_id)
    dek = await crypto.get_dek(session, tenant_id)
    await session.execute(delete(ParkingVehicle).where(ParkingVehicle.tenant_id == tenant_id))

    matched = 0
    unmatched: list[str] = []
    for row in vehicles:
        unit_no = _unit_no(row["ho"])
        household_id = (
            index.get((_building_name(row["dong"]), unit_no)) if unit_no is not None else None
        )
        if household_id is None:
            unmatched.append(f"{row['dong']}-{row['ho']}")
            continue
        session.add(
            ParkingVehicle(
                tenant_id=tenant_id,
                household_id=household_id,
                plate_enc=crypto.encrypt(dek, str(row["plate"]).strip()),
                model=(str(row["model"]).strip() or None) if row.get("model") else None,
                is_ev=bool(row.get("ev")),
            )
        )
        matched += 1
    await session.flush()
    return matched, unmatched


def _layout_spots(layout: dict[str, Any]) -> list[Spot]:
    return [
        Spot(no=str(s["no"]), kind=str(s["kind"]), x=float(s["x"]), y=float(s["y"]))
        for s in layout["spots"]
    ]


def _layout_cores(layout: dict[str, Any]) -> list[Core]:
    return [
        Core(
            name=str(c["name"]),
            x=float(c["x"]),
            y=float(c["y"]),
            w=float(c["w"]),
            h=float(c["h"]),
        )
        for c in layout["cores"]
    ]


async def _vehicle_refs(session: AsyncSession, tenant_id: uuid.UUID) -> list[VehicleRef]:
    """적재된 입주민 차 → 배정용 참조(동명은 코어명 "401동"과 맞춘다). 번호판 평문 없음."""
    rows = await session.execute(
        select(ParkingVehicle.id, Building.name, ParkingVehicle.is_ev)
        .join(Household, Household.id == ParkingVehicle.household_id)
        .join(Building, Building.id == Household.building_id)
        .where(ParkingVehicle.tenant_id == tenant_id)
    )
    return [
        VehicleRef(vehicle_id=str(vid), dong=f"{name}동", is_ev=bool(is_ev))
        for vid, name, is_ev in rows
    ]


def _occupancy_row(
    crypto: PiiCrypto, dek: bytes, tenant_id: uuid.UUID, occ: Occupancy
) -> ParkingOccupancy:
    """Occupancy(순수 배정) → 영속 행. 외부차 번호판은 암호문으로만 저장한다(규칙 2)."""
    if occ.is_external:
        assert occ.external_plate is not None and occ.vehicle_id is None
        return ParkingOccupancy(
            tenant_id=tenant_id,
            spot_no=occ.spot_no,
            is_external=True,
            parking_vehicle_id=None,
            external_plate_enc=crypto.encrypt(dek, occ.external_plate),
            parked_hours=occ.parked_hours,
        )
    assert occ.vehicle_id is not None and occ.external_plate is None
    return ParkingOccupancy(
        tenant_id=tenant_id,
        spot_no=occ.spot_no,
        is_external=False,
        parking_vehicle_id=uuid.UUID(occ.vehicle_id),
        external_plate_enc=None,
        parked_hours=occ.parked_hours,
    )


async def _replace_occupancy(
    session: AsyncSession,
    crypto: PiiCrypto,
    tenant_id: uuid.UUID,
    layout: dict[str, Any],
) -> tuple[int, int, int]:
    """점유 전량 교체 — 결정적 배정을 계산해 면당 1행 적재. (입주민, 외부, 빈 면) 반환."""
    vehicles = await _vehicle_refs(session, tenant_id)
    occupancies = assign_occupancy(_layout_spots(layout), _layout_cores(layout), vehicles)
    # 불변식: 면당 1행(spot_no 유니크) — CHECK/UNIQUE 위반 방어(_occupancy_row가 CHECK도 assert).
    spot_nos = [o.spot_no for o in occupancies]
    assert len(spot_nos) == len(set(spot_nos)), "spot_no가 중복 배정됨"

    dek = await crypto.get_dek(session, tenant_id)
    await session.execute(delete(ParkingOccupancy).where(ParkingOccupancy.tenant_id == tenant_id))
    for occ in occupancies:
        session.add(_occupancy_row(crypto, dek, tenant_id, occ))
    await session.flush()

    resident = sum(1 for o in occupancies if not o.is_external)
    external = sum(1 for o in occupancies if o.is_external)
    empty = len(layout["spots"]) - len(occupancies)
    return resident, external, empty


def _report(
    layout: dict[str, Any],
    total: int,
    matched: int,
    unmatched: list[str],
    occupancy: tuple[int, int, int],
) -> None:
    print(
        f"배치도: 주차면 {len(layout['spots'])}면 · 동 {len(layout['buildings'])} · "
        f"코어 {len(layout['cores'])} · 안내 {len(layout['boxes'])} (viewBox {layout['viewBox']})"
    )
    print(f"차량: 총 {total} · 매칭 {matched} · 미매칭 {len(unmatched)}")
    if unmatched:
        samples = unmatched[:MAX_UNMATCHED_SAMPLES]
        print(f"  미매칭 표본({len(samples)}/{len(unmatched)}): {', '.join(samples)}")
    resident, external, empty = occupancy
    print(
        f"점유: 총 {len(layout['spots'])}면 · 점유 {resident + external}"
        f"(입주민 {resident} · 외부 {external}) · 빈 면 {empty}"
    )


async def _run(tenant_id: uuid.UUID) -> None:
    layout = _load_layout()
    vehicles = _load_vehicles()
    crypto = get_pii_crypto()
    engine = create_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            if await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id)) is None:
                raise SystemExit(f"단지를 찾을 수 없습니다: {tenant_id}")
            # 소유자(liviq) 접속은 RLS를 우회하지만 get_dek 계약에 맞춰 컨텍스트를 설정한다.
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            await _replace_layout(session, tenant_id, layout)
            matched, unmatched = await _replace_vehicles(session, crypto, tenant_id, vehicles)
            occupancy = await _replace_occupancy(session, crypto, tenant_id, layout)
        _report(layout, len(vehicles), matched, unmatched, occupancy)
        print(f"단지: {tenant_id}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="지하주차장 배치도·차량 시드(H9-5)")
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        default=DEFAULT_TENANT_ID,
        help=f"대상 단지 UUID (기본: 첫마을 4단지 {DEFAULT_TENANT_ID})",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.tenant_id))


if __name__ == "__main__":
    main()
