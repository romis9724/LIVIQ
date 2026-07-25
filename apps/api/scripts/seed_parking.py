"""seed_parking.py — 지하주차장 배치도·입주민 차량 시드 (H9-5).

프로토타입 배치도(442면)와 입주민 차량(348대)을 DB에 적재한다. 배치도는 단지당 1행,
차량은 명부(households) 매칭분만 — 둘 다 delete-then-insert 전량 교체(단일 트랜잭션)라
재실행해도 개수가 늘지 않는다. 차량번호는 봉투 암호화해 plate_enc에만 저장한다(규칙 2).

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

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import Building, Household, ParkingLayout, ParkingVehicle, Tenant

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


def _report(layout: dict[str, Any], total: int, matched: int, unmatched: list[str]) -> None:
    print(
        f"배치도: 주차면 {len(layout['spots'])}면 · 동 {len(layout['buildings'])} · "
        f"코어 {len(layout['cores'])} · 안내 {len(layout['boxes'])} (viewBox {layout['viewBox']})"
    )
    print(f"차량: 총 {total} · 매칭 {matched} · 미매칭 {len(unmatched)}")
    if unmatched:
        samples = unmatched[:MAX_UNMATCHED_SAMPLES]
        print(f"  미매칭 표본({len(samples)}/{len(unmatched)}): {', '.join(samples)}")


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
        _report(layout, len(vehicles), matched, unmatched)
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
