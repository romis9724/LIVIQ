"""주차 점유 기하·배정 — 순수 함수(H15-4, ADR-0023).

DB·I/O·crypto 없음. 도구(SQLAlchemy fetch)·시더(seed_parking.py)·gen_labels(asyncpg fetch)가
공유하는 결정적 계산만 담는다(진실 이원화 차단). 번호판은 평문 문자열만 반환 — 암호화는 시더 몫.
"""

from __future__ import annotations

from ai_core.parking.geometry import (
    PX_TO_M,
    SPOT_H,
    SPOT_W,
    Core,
    NearestSpot,
    Occupancy,
    Spot,
    VehicleRef,
    assign_occupancy,
    core_center,
    cores_from_layout,
    distance_px,
    nearest_available_spots,
    spot_center,
    spots_from_layout,
)

__all__ = [
    "PX_TO_M",
    "SPOT_H",
    "SPOT_W",
    "Core",
    "NearestSpot",
    "Occupancy",
    "Spot",
    "VehicleRef",
    "assign_occupancy",
    "core_center",
    "cores_from_layout",
    "distance_px",
    "nearest_available_spots",
    "spot_center",
    "spots_from_layout",
]
