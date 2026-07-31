"""주차 점유 배정 규칙 (H16) — DB 없이 seed_parking의 순수 배정 함수만 검증.

적재(DB round-trip)는 test_parking.py·시드 실행이 담당한다. 여기서는 규칙만 본다:
결정성(고정 시드)·면 중복 없음·장애인면 미배정·전기차면 EV 전용·외부 차량 8대 번호판 유일.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

# scripts/는 패키지가 아니라 import path에 직접 추가(다른 스크립트 테스트와 동일 관행).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from seed_parking import (  # noqa: E402
    EXTERNAL_COUNT,
    LAYOUT_FILE,
    VEHICLES_FILE,
    Occupancy,
    assign_occupancy,
)

_LAYOUT = json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
_VEHICLES = json.loads(VEHICLES_FILE.read_text(encoding="utf-8"))
_NOW = datetime.datetime(2026, 7, 31, 9, 0, tzinfo=datetime.UTC)
_PLATES = {row["plate"] for row in _VEHICLES}
_SPOT_KIND = {spot["no"]: spot["kind"] for spot in _LAYOUT["spots"]}


def _assign() -> Occupancy:
    return assign_occupancy(_LAYOUT, _VEHICLES, set(_PLATES), _NOW)


def test_assignment_is_deterministic() -> None:
    """고정 시드 — 두 번 돌려도 같은 면·같은 번호판(시드 재실행 멱등의 근거)."""
    first, second = _assign(), _assign()
    assert first == second


def test_spots_are_not_double_booked() -> None:
    """한 면에 두 대 없음 — 부분 유니크 위반이 시드 단계에서 나면 안 된다."""
    used = [slot[0] for slot in _assign().resident if slot] + [
        car.spot_no for car in _assign().external
    ]
    assert len(used) == len(set(used))


def test_spot_kind_rules() -> None:
    """장애인면은 배정 금지, 전기차면은 EV 차량만."""
    occupancy = _assign()
    for vehicle, slot in zip(_VEHICLES, occupancy.resident, strict=True):
        if slot is None:
            continue
        kind = _SPOT_KIND[slot[0]]
        assert kind != "장애인"
        if kind == "전기차":
            assert vehicle["ev"] is True
    for car in occupancy.external:
        assert _SPOT_KIND[car.spot_no] == "일반"  # 외부 차량은 EV 아님


def test_occupancy_rate_and_entry_window() -> None:
    """재실률 0.75 근사(±5%p) · 입주민 입차는 0.5~14시간 전."""
    occupancy = _assign()
    parked = [slot for slot in occupancy.resident if slot]
    assert abs(len(parked) / len(_VEHICLES) - 0.75) < 0.05
    for _, entry_at in parked:
        hours = (_NOW - entry_at).total_seconds() / 3600
        assert 0.5 <= hours <= 14.0


def test_external_cars_are_distinct_and_long_stay() -> None:
    """외부 8대 — 번호판이 입주민과 겹치지 않고, 절반은 장기(20h 이상) 주차."""
    external = _assign().external
    assert len(external) == EXTERNAL_COUNT
    plates = {car.plate for car in external}
    assert len(plates) == EXTERNAL_COUNT
    assert not (plates & _PLATES)
    long_stay = [c for c in external if (_NOW - c.entry_at).total_seconds() / 3600 >= 20]
    assert len(long_stay) == EXTERNAL_COUNT // 2
