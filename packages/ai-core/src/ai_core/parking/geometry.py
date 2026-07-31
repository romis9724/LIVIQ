"""주차 면 점유 배정·최근접 빈자리 — 순수 결정적 기하(H15-4, ADR-0023).

`apps/web-admin/src/features/parking/parking-sim.ts`의 dist·pick·entranceOf·simulateParking을
난수를 제거한 결정적 형태로 이식한다. 좌표계·축척은 프론트와 동일해야 배치도 좌표가 맞는다.

- 배정(assign_occupancy): 입주민 차는 자기 동 코어에서 가까운 빈 면 우선, 장애인 면 미배정·전기차
  면은 EV만. 외부차 external_count대는 입구 근처. 정렬 기반 결정적(동·차량ID·면번호 tie-break).
- 최근접(nearest_available_spots): 내 동 코어 중심에서 가까운 빈 면 top_k(EV 선호 시 전기차 포함).

거리는 면 중심↔점 유클리드(px), 표시용 m은 px·PX_TO_M 반올림. 난수·시각 의존 없음(재현 가능).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from math import hypot

# 배치도 축척 — 면 1개 34x64px = 2.5m x 5.0m (13px/m). 프론트 parking-sim.ts와 동일해야 한다.
SPOT_W = 34
SPOT_H = 64
PX_TO_M = 1 / 13

# 외부차 기본 대수(방치 차량 시나리오) — parking-sim.ts EXTERNAL_COUNT와 동일.
_DEFAULT_EXTERNAL_COUNT = 8
# 결정적 가짜 번호판 문자 집합(입주민 평문 번호판은 이 모듈에 없음 — 외부끼리만 유니크 보장).
_PLATE_LETTERS = "가나다라마거너더러머버서어저허"
# 입주민 주차 경과(시간) 결정적 순환폭 — 0.5~14.0시간을 idx로 재현.
_RESIDENT_HOURS_STEPS = 28

_KIND_DISABLED = "장애인"
_KIND_EV = "전기차"
_KIND_NORMAL = "일반"


@dataclass(frozen=True)
class Spot:
    """배치도 면 1개. kind는 "일반"·"장애인"·"전기차". (x, y)는 좌상단 좌표(px)."""

    no: str
    kind: str
    x: float
    y: float


@dataclass(frozen=True)
class Core:
    """동 코어(엘리베이터 홀 등) 사각 영역 — 입주민 근접 배정의 앵커. name은 동명(예 "401동")."""

    name: str
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class VehicleRef:
    """배정 대상 입주민 차 참조 — 번호판 평문은 담지 않는다(암호화는 시더 몫)."""

    vehicle_id: str
    dong: str
    is_ev: bool


@dataclass(frozen=True)
class Occupancy:
    """배정 결과 1건. 입주민은 vehicle_id, 외부차는 external_plate(평문)만 채워진다."""

    spot_no: str
    is_external: bool
    vehicle_id: str | None
    external_plate: str | None
    parked_hours: float


@dataclass(frozen=True)
class NearestSpot:
    """최근접 빈자리 1건 — 면 번호·종류·코어까지 거리(m, 반올림)."""

    no: str
    kind: str
    distance_m: int


def spot_center(s: Spot) -> tuple[float, float]:
    """면 중심 좌표(px)."""
    return (s.x + SPOT_W / 2, s.y + SPOT_H / 2)


def core_center(c: Core) -> tuple[float, float]:
    """코어 사각 영역 중심 좌표(px)."""
    return (c.x + c.w / 2, c.y + c.h / 2)


def distance_px(spot: Spot, cx: float, cy: float) -> float:
    """면 중심 ↔ 점 (cx, cy) 유클리드 거리(px)."""
    sx, sy = spot_center(spot)
    return hypot(sx - cx, sy - cy)


def _entrance_center(spots: list[Spot]) -> tuple[float, float] | None:
    """입구(진입 램프) 근사 중심 — 배치도 좌하단(entranceOf 이식). 면이 없으면 None."""
    if not spots:
        return None
    min_x = min(s.x for s in spots)
    max_y = max(s.y for s in spots)
    # rect = {x: min_x, y: max_y + SPOT_H, w: 160, h: 64}
    return (min_x + 160 / 2, max_y + SPOT_H + 64 / 2)


def _resident_candidate(spot: Spot, taken: set[str], is_ev: bool) -> bool:
    """입주민 배정 후보 여부 — 미점유·장애인 면 제외·전기차 면은 EV만."""
    if spot.no in taken or spot.kind == _KIND_DISABLED:
        return False
    return spot.kind != _KIND_EV or is_ev


def _external_candidate(spot: Spot, taken: set[str]) -> bool:
    """외부차 배정 후보 — 미점유·장애인 면 제외·전기차 면 제외(외부는 EV 취급 안 함)."""
    if spot.no in taken or spot.kind == _KIND_DISABLED:
        return False
    return spot.kind != _KIND_EV


def _pick_nearest(
    spots: list[Spot],
    anchor: tuple[float, float] | None,
    is_candidate: Callable[[Spot], bool],
) -> Spot | None:
    """후보 면 중 앵커 최근접(앵커 없으면 x 최소). 동점은 면번호 오름차순. 없으면 None."""
    best: Spot | None = None
    best_key: tuple[float, str] | None = None
    for s in spots:
        if not is_candidate(s):
            continue
        score = distance_px(s, *anchor) if anchor is not None else float(s.x)
        key = (score, s.no)
        if best_key is None or key < best_key:
            best_key = key
            best = s
    return best


def _external_plate(index: int, used: set[str]) -> str:
    """외부끼리 유니크한 결정적 가짜 번호판. 충돌 시 오프셋을 늘려 재현 가능하게 회피."""
    n = index
    while True:
        letter = _PLATE_LETTERS[n % len(_PLATE_LETTERS)]
        plate = f"{100 + n * 37}{letter}{1000 + n * 137}"
        if plate not in used:
            return plate
        n += 1


def assign_occupancy(
    spots: list[Spot],
    cores: list[Core],
    vehicles: list[VehicleRef],
    *,
    external_count: int = _DEFAULT_EXTERNAL_COUNT,
) -> list[Occupancy]:
    """결정적 점유 배정 — 입주민 자기 동 근접 + 외부차 입구 근접. 입력 순서 무관(정렬 기반)."""
    core_by_dong = {c.name: c for c in cores}
    taken: set[str] = set()
    result: list[Occupancy] = []

    ordered = sorted(vehicles, key=lambda v: (v.dong, v.vehicle_id))
    for idx, vehicle in enumerate(ordered):
        core = core_by_dong.get(vehicle.dong)
        anchor = core_center(core) if core is not None else None
        spot = _pick_nearest(
            spots,
            anchor,
            partial(_resident_candidate, taken=taken, is_ev=vehicle.is_ev),
        )
        if spot is None:
            break  # 면이 소진되면 나머지 입주민 차는 미배정(프론트 pick None과 동일)
        taken.add(spot.no)
        result.append(
            Occupancy(
                spot_no=spot.no,
                is_external=False,
                vehicle_id=vehicle.vehicle_id,
                external_plate=None,
                parked_hours=0.5 + (idx % _RESIDENT_HOURS_STEPS) * 0.5,
            )
        )

    entrance = _entrance_center(spots)
    used_plates: set[str] = set()
    for i in range(external_count):
        spot = _pick_nearest(spots, entrance, partial(_external_candidate, taken=taken))
        if spot is None:
            break
        plate = _external_plate(i, used_plates)
        used_plates.add(plate)
        taken.add(spot.no)
        # 짝수는 단기·홀수는 장기(방치 차량 식별 시나리오) — parking-sim.ts 분기 이식.
        parked_hours = float(1 + i) if i % 2 == 0 else float(20 + i)
        result.append(
            Occupancy(
                spot_no=spot.no,
                is_external=True,
                vehicle_id=None,
                external_plate=plate,
                parked_hours=parked_hours,
            )
        )

    return result


def nearest_available_spots(
    spots: list[Spot],
    cores: list[Core],
    occupied_spot_nos: set[str],
    core_name: str,
    *,
    ev_preferred: bool = False,
    top_k: int = 3,
) -> list[NearestSpot]:
    """내 동 코어 중심에서 가까운 빈 면 top_k. EV 선호 시 전기차 면 포함, 아니면 일반 면만."""
    anchor_core = next((c for c in cores if c.name == core_name), None)
    if anchor_core is None:
        return []
    anchor = core_center(anchor_core)

    def _is_free(s: Spot) -> bool:
        if s.no in occupied_spot_nos or s.kind == _KIND_DISABLED:
            return False
        return s.kind == _KIND_NORMAL or (s.kind == _KIND_EV and ev_preferred)

    free = [s for s in spots if _is_free(s)]
    free.sort(key=lambda s: (distance_px(s, *anchor), s.no))
    return [
        NearestSpot(no=s.no, kind=s.kind, distance_m=round(distance_px(s, *anchor) * PX_TO_M))
        for s in free[:top_k]
    ]
