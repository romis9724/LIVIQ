"""seed_parking.py — 지하주차장 배치도·차량·점유 시드 (H9-5 · 점유 H16).

프로토타입 배치도(442면)와 입주민 차량(348대)을 DB에 적재하고, 어느 차가 어느 면에
언제부터 서 있는지(spot_no·entry_at)까지 결정적으로 배정한다(H16 — 프론트 시뮬 폐기,
점유의 단일 출처는 DB). 배치도는 단지당 1행, 차량은 명부(households) 매칭분 + 외부 차량
8대 — 전부 delete-then-insert 전량 교체(단일 트랜잭션)라 재실행해도 개수가 늘지 않는다.
차량번호는 봉투 암호화해 plate_enc에만 저장한다(규칙 2).

입력은 `scripts/data/`의 추출물:
  - parking_layout.json   viewBox·buildings·boxes·cores·spots (렌더 페이로드 그대로)
  - parking_vehicles.json [{"plate","dong","ho","model","ev"}]

차량 dong("401동")·ho("1502호")를 명부 (buildings.name, households.unit_no)에 매칭한다
(seed_households_xlsx·twin과 동일 정규화). 미매칭은 스킵하고 리포트에 표본을 남긴다.

배정 규칙은 폐기한 프론트 시뮬(parking-sim.ts)과 같다 — 재실률 0.75·자기 동 코어 근처 선호·
장애인면 미배정·전기차면은 EV 전용·외부 차량은 입구 근처 선호에 절반은 장기 주차. 고정 시드
PRNG라 결과가 결정적이지만, JS 구현과의 비트 일치는 요구하지 않는다(재실행 멱등이면 충분).

실행(DATABASE_URL·PII_MASTER_KEY는 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync python scripts/seed_parking.py [--tenant-id <uuid>]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import math
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
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

# ── 점유 배정 상수 (parking-sim.ts와 동일 값) ─────────────────────────────────
OCCUPANCY_SEED = 20260725  # 고정 시드 — 재실행해도 같은 배치
OCCUPANCY_RATE = 0.75  # 입주민 차량 재실률
SPOT_W, SPOT_H = 34, 64  # 면 1개 34x64px = 2.5m x 5.0m (중심 계산용)
PICK_JITTER_PX = 500  # 근처 선호 스코어에 섞는 무작위 편차
EXTERNAL_COUNT = 8  # 외부(방문·방치) 차량 대수
PLATE_ATTEMPTS = 50  # 번호판 중복 회피 재시도 상한
PLATE_LETTERS = "가나다라마거너더러머버서어저허"
_ENTRANCE_W, _ENTRANCE_H = 160, 64  # 진입 램프 근사 박스


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


# ── 결정적 점유 배정 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExternalCar:
    """명부에 없는 외부 차량 1대 — 번호판만 있고 세대·차종은 없다."""

    plate: str
    spot_no: str
    entry_at: datetime.datetime


@dataclass(frozen=True)
class Occupancy:
    """배정 결과. resident[i]는 입력 차량 i의 (면 번호, 입차시각) 또는 None(미주차)."""

    resident: tuple[tuple[str, datetime.datetime] | None, ...]
    external: tuple[ExternalCar, ...]

    @property
    def parked(self) -> int:
        return sum(1 for slot in self.resident if slot is not None) + len(self.external)


def _center_dist(spot: dict[str, Any], rect: dict[str, Any]) -> float:
    """면 중심 ↔ 사각 영역(코어·입구) 중심 거리(px)."""
    return math.hypot(
        spot["x"] + SPOT_W / 2 - (rect["x"] + rect["w"] / 2),
        spot["y"] + SPOT_H / 2 - (rect["y"] + rect["h"] / 2),
    )


def _entrance_of(spots: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """입구(진입 램프) 근사 — 배치도 좌하단(parking-sim.entranceOf와 동일 근사)."""
    if not spots:
        return None
    return {
        "x": min(spot["x"] for spot in spots),
        "y": max(spot["y"] for spot in spots) + SPOT_H,
        "w": _ENTRANCE_W,
        "h": _ENTRANCE_H,
    }


def _pick_spot(
    rand: random.Random,
    spots: Sequence[dict[str, Any]],
    taken: set[str],
    *,
    is_ev: bool,
    near: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """near 근처 선호 + 무작위 편차. 최저 스코어 면(동점이면 앞선 면). 남은 면 없으면 None."""
    best: dict[str, Any] | None = None
    best_score = math.inf
    for spot in spots:
        if spot["no"] in taken or spot["kind"] == "장애인":
            continue
        if spot["kind"] == "전기차" and not is_ev:
            continue
        base = _center_dist(spot, near) if near else spot["x"]
        score = base + rand.random() * PICK_JITTER_PX
        if score < best_score:
            best_score = score
            best = spot
    return best


def _next_external_plate(rand: random.Random, used: set[str]) -> str | None:
    """기존 번호판과 겹치지 않는 임의 번호판. 상한까지 중복이면 None(그 대수는 건너뛴다)."""
    for _ in range(PLATE_ATTEMPTS):
        plate = (
            f"{rand.randrange(100, 1000)}"
            f"{PLATE_LETTERS[rand.randrange(len(PLATE_LETTERS))]}"
            f"{rand.randrange(1000, 10000)}"
        )
        if plate not in used:
            return plate
    return None


def assign_occupancy(
    layout: dict[str, Any],
    vehicles: Sequence[dict[str, Any]],
    known_plates: set[str],
    now: datetime.datetime,
) -> Occupancy:
    """차량을 주차면에 결정적으로 배정한다(고정 시드 — 재실행 시 같은 배치).

    입주민 차량은 재실률만큼만 주차하고 자기 동 코어 근처를 선호한다. 장애인면은 배정하지
    않고, 전기차 충전면은 EV만 배정한다. 외부 차량 8대는 입구 근처 선호에 절반은 장기 주차
    (20~72h — 방치 차량 식별 시나리오).
    """
    rand = random.Random(OCCUPANCY_SEED)  # noqa: S311 — 보안용 아님, 결정적 시드 데이터
    spots: Sequence[dict[str, Any]] = layout["spots"]
    core_by_dong = {core["name"]: core for core in layout["cores"]}
    taken: set[str] = set()
    plates = set(known_plates)

    resident: list[tuple[str, datetime.datetime] | None] = []
    for vehicle in vehicles:
        spot = None
        if rand.random() < OCCUPANCY_RATE:
            spot = _pick_spot(
                rand,
                spots,
                taken,
                is_ev=bool(vehicle.get("ev")),
                near=core_by_dong.get(str(vehicle["dong"])),
            )
        if spot is None:
            resident.append(None)
            continue
        taken.add(spot["no"])
        hours = 0.5 + rand.random() * 13.5
        resident.append((spot["no"], now - datetime.timedelta(hours=hours)))

    entrance = _entrance_of(spots)
    external: list[ExternalCar] = []
    for i in range(EXTERNAL_COUNT):
        plate = _next_external_plate(rand, plates)
        if plate is None:
            continue
        spot = _pick_spot(rand, spots, taken, is_ev=False, near=entrance)
        if spot is None:
            break
        taken.add(spot["no"])
        plates.add(plate)
        # 절반은 장기 주차(20~72시간) — 방치 차량 식별 시나리오.
        hours = 1 + rand.random() * 8 if i % 2 == 0 else 20 + rand.random() * 52
        external.append(
            ExternalCar(
                plate=plate, spot_no=spot["no"], entry_at=now - datetime.timedelta(hours=hours)
            )
        )

    return Occupancy(resident=tuple(resident), external=tuple(external))


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
    layout: dict[str, Any],
    now: datetime.datetime,
) -> tuple[int, list[str], Occupancy]:
    """차량 전량 교체 — 명부 매칭분 + 외부 차량. (매칭 수, 미매칭 표본, 배정) 반환."""
    index = await _household_index(session, tenant_id)
    dek = await crypto.get_dek(session, tenant_id)
    await session.execute(delete(ParkingVehicle).where(ParkingVehicle.tenant_id == tenant_id))

    matched_rows: list[tuple[dict[str, Any], uuid.UUID]] = []
    unmatched: list[str] = []
    for row in vehicles:
        unit_no = _unit_no(row["ho"])
        household_id = (
            index.get((_building_name(row["dong"]), unit_no)) if unit_no is not None else None
        )
        if household_id is None:
            unmatched.append(f"{row['dong']}-{row['ho']}")
            continue
        matched_rows.append((row, household_id))

    known_plates = {str(row["plate"]).strip() for row in vehicles}
    occupancy = assign_occupancy(layout, [row for row, _ in matched_rows], known_plates, now)

    for (row, household_id), parked in zip(matched_rows, occupancy.resident, strict=True):
        session.add(
            ParkingVehicle(
                tenant_id=tenant_id,
                household_id=household_id,
                plate_enc=crypto.encrypt(dek, str(row["plate"]).strip()),
                model=(str(row["model"]).strip() or None) if row.get("model") else None,
                is_ev=bool(row.get("ev")),
                spot_no=parked[0] if parked else None,
                entry_at=parked[1] if parked else None,
            )
        )
    for car in occupancy.external:
        session.add(
            ParkingVehicle(
                tenant_id=tenant_id,
                household_id=None,  # 명부에 없는 외부 차량(H16)
                plate_enc=crypto.encrypt(dek, car.plate),
                model=None,
                is_ev=False,
                spot_no=car.spot_no,
                entry_at=car.entry_at,
            )
        )
    await session.flush()
    return len(matched_rows), unmatched, occupancy


def _report(
    layout: dict[str, Any],
    total: int,
    matched: int,
    unmatched: list[str],
    occupancy: Occupancy,
) -> None:
    spots = len(layout["spots"])
    print(
        f"배치도: 주차면 {spots}면 · 동 {len(layout['buildings'])} · "
        f"코어 {len(layout['cores'])} · 안내 {len(layout['boxes'])} (viewBox {layout['viewBox']})"
    )
    external = len(occupancy.external)
    parked = occupancy.parked
    print(f"차량: 총 {total} · 매칭 {matched} · 미매칭 {len(unmatched)} · 외부 {external}")
    print(f"점유: 주차 {parked}면 · 빈 면 {spots - parked} (시드 {OCCUPANCY_SEED})")
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
            matched, unmatched, occupancy = await _replace_vehicles(
                session, crypto, tenant_id, vehicles, layout, datetime.datetime.now(datetime.UTC)
            )
        _report(layout, len(vehicles), matched, unmatched, occupancy)
        print(f"단지: {tenant_id}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="지하주차장 배치도·차량·점유 시드(H9-5·H16)")
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
