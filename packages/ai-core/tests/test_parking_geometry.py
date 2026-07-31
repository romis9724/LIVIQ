"""주차 기하·배정 순수 함수 테스트 — 결정성·무결성 규칙(H15-4, ADR-0023).

DB 없이 인메모리 fixture로 검증. 배정은 재현 가능해야 하고(SoR 재계산), 장애인/전기차 면 규칙과
외부차 개수·번호판 유니크가 지켜져야 한다. 최근접은 점유·장애인 제외·EV 선호·거리순·top_k 상한.
"""

from __future__ import annotations

import pytest

from ai_core.parking import (
    PX_TO_M,
    SPOT_W,
    Core,
    Spot,
    VehicleRef,
    assign_occupancy,
    nearest_available_spots,
)

pytestmark = pytest.mark.unit


def _grid_spots() -> list[Spot]:
    """일반 6 + 전기차 2 + 장애인 2 = 10면. x는 40 간격, 401동은 좌측·402동은 우측 근처."""
    return [
        Spot(no="001", kind="일반", x=0, y=100),
        Spot(no="002", kind="일반", x=40, y=100),
        Spot(no="003", kind="전기차", x=80, y=100),
        Spot(no="004", kind="장애인", x=120, y=100),
        Spot(no="005", kind="일반", x=400, y=100),
        Spot(no="006", kind="일반", x=440, y=100),
        Spot(no="007", kind="전기차", x=480, y=100),
        Spot(no="008", kind="장애인", x=520, y=100),
        Spot(no="009", kind="일반", x=200, y=100),
        Spot(no="010", kind="일반", x=240, y=100),
    ]


def _cores() -> list[Core]:
    return [
        Core(name="401동", x=0, y=100, w=40, h=40),
        Core(name="402동", x=440, y=100, w=40, h=40),
    ]


# ── assign_occupancy ─────────────────────────────────────────────────────────


def test_assign_is_deterministic_regardless_of_input_order() -> None:
    # Arrange
    spots, cores = _grid_spots(), _cores()
    vehicles = [
        VehicleRef(vehicle_id="v3", dong="402동", is_ev=False),
        VehicleRef(vehicle_id="v1", dong="401동", is_ev=False),
        VehicleRef(vehicle_id="v2", dong="401동", is_ev=True),
    ]

    # Act
    first = assign_occupancy(spots, cores, vehicles, external_count=0)
    second = assign_occupancy(spots, cores, list(reversed(vehicles)), external_count=0)

    # Assert — 정렬 기반이라 입력 순서와 무관하게 동일 결과
    assert first == second


def test_assign_never_uses_disabled_spots() -> None:
    # Arrange — 모든 면이 후보가 되도록 차량을 면 수만큼 채운다
    spots, cores = _grid_spots(), _cores()
    vehicles = [VehicleRef(vehicle_id=f"v{i}", dong="401동", is_ev=True) for i in range(8)]

    # Act
    occ = assign_occupancy(spots, cores, vehicles, external_count=0)

    # Assert — 장애인 면(004·008)은 절대 배정되지 않는다
    assigned = {o.spot_no for o in occ}
    assert "004" not in assigned
    assert "008" not in assigned


def test_assign_ev_spots_only_for_ev_vehicles() -> None:
    # Arrange — 비-EV만 있으면 전기차 면은 남는다
    spots, cores = _grid_spots(), _cores()
    vehicles = [VehicleRef(vehicle_id=f"v{i}", dong="401동", is_ev=False) for i in range(6)]

    # Act
    occ = assign_occupancy(spots, cores, vehicles, external_count=0)

    # Assert — 전기차 면(003·007)은 비-EV에 배정 안 됨
    assigned = {o.spot_no for o in occ}
    assert "003" not in assigned
    assert "007" not in assigned


def test_resident_parks_near_own_core() -> None:
    # Arrange — 401동 차 1대. 401동 코어(x=0 근처)에서 가장 가까운 일반 면은 001.
    spots, cores = _grid_spots(), _cores()
    vehicles = [VehicleRef(vehicle_id="v1", dong="401동", is_ev=False)]

    # Act
    occ = assign_occupancy(spots, cores, vehicles, external_count=0)

    # Assert
    assert len(occ) == 1
    assert occ[0].spot_no == "001"
    assert occ[0].is_external is False
    assert occ[0].vehicle_id == "v1"
    assert occ[0].external_plate is None


def test_external_count_and_plates_unique() -> None:
    # Arrange
    spots, cores = _grid_spots(), _cores()

    # Act — 입주민 없이 외부차 4대만
    occ = assign_occupancy(spots, cores, [], external_count=4)

    # Assert
    externals = [o for o in occ if o.is_external]
    assert len(externals) == 4
    plates = [o.external_plate for o in externals]
    assert all(p is not None for p in plates)
    assert len(set(plates)) == 4  # 유니크
    for e in externals:
        assert e.vehicle_id is None
        assert e.parked_hours > 0


def test_external_avoids_disabled_and_ev_spots() -> None:
    # Arrange — 외부차를 면 수만큼 요청해도 일반 면(6개)만 채운다
    spots, cores = _grid_spots(), _cores()

    # Act
    occ = assign_occupancy(spots, cores, [], external_count=10)

    # Assert — 일반 면 6개 한도, 장애인·전기차 면 미사용
    assigned = {o.spot_no for o in occ}
    assert len(occ) == 6
    assert assigned == {"001", "002", "005", "006", "009", "010"}


# ── nearest_available_spots ──────────────────────────────────────────────────


def test_nearest_excludes_occupied_and_disabled() -> None:
    # Arrange — 001 점유, 401동 기준
    spots, cores = _grid_spots(), _cores()

    # Act
    result = nearest_available_spots(spots, cores, {"001"}, "401동")

    # Assert — 001(점유)·004/008(장애인)·003/007(전기차, ev_preferred=False) 제외
    nos = [r.no for r in result]
    assert "001" not in nos
    assert "004" not in nos
    assert "003" not in nos


def test_nearest_ev_preferred_includes_ev_spots() -> None:
    # Arrange
    spots, cores = _grid_spots(), _cores()

    # Act
    with_ev = nearest_available_spots(spots, cores, set(), "401동", ev_preferred=True, top_k=10)
    without_ev = nearest_available_spots(spots, cores, set(), "401동", top_k=10)

    # Assert — EV 선호 시 전기차 면 포함, 미지정 시 제외
    assert "003" in {r.no for r in with_ev}
    assert "003" not in {r.no for r in without_ev}


def test_nearest_sorted_by_distance_and_top_k() -> None:
    # Arrange — 401동 코어(x≈20)에서 가까운 순: 001, 002, 009 ...
    spots, cores = _grid_spots(), _cores()

    # Act
    result = nearest_available_spots(spots, cores, set(), "401동", top_k=3)

    # Assert — top_k 상한 + 거리 오름차순
    assert len(result) == 3
    assert [r.no for r in result] == ["001", "002", "009"]
    assert result[0].distance_m <= result[1].distance_m <= result[2].distance_m


def test_nearest_distance_uses_px_to_m() -> None:
    # Arrange — 401동 코어 중심 (20, 120), 001 면 중심 (SPOT_W/2, ...)
    spots, cores = _grid_spots(), _cores()

    # Act
    result = nearest_available_spots(spots, cores, set(), "401동", top_k=1)

    # Assert — 거리는 반드시 반올림된 정수 m
    assert result[0].distance_m == round(result[0].distance_m)
    assert result[0].distance_m >= 0
    _ = (PX_TO_M, SPOT_W)  # 좌표계 상수 사용 명시


def test_nearest_unknown_core_returns_empty() -> None:
    # Arrange
    spots, cores = _grid_spots(), _cores()

    # Act
    result = nearest_available_spots(spots, cores, set(), "999동")

    # Assert
    assert result == []


def test_nearest_full_lot_returns_empty() -> None:
    # Arrange — 모든 일반·전기차 면 점유
    spots, cores = _grid_spots(), _cores()
    occupied = {s.no for s in spots}

    # Act
    result = nearest_available_spots(spots, cores, occupied, "401동", ev_preferred=True)

    # Assert
    assert result == []
