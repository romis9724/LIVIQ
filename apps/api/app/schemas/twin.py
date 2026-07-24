"""twin 계약 — units.json 업로드 파싱·geometry 조회·오버레이 (H9-1, ADR-0019).

업로드는 units.json의 세대 3D 폴리곤을 명부(households) 매칭분만 적재한다(geometry만 신규,
세대·세대원은 기존 명부 재사용). 조회는 building/floor/unit을 조인해 렌더용으로 노출한다.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class TwinUnitIn(BaseModel):
    """units.json unit 1건 — 렌더에 쓰는 필드만 검증(나머지는 무시)."""

    model_config = ConfigDict(extra="ignore")

    dong: str
    floor: int
    ho: int
    unit_type: str | None = None
    area_m2: float | None = None
    polygon_2d: list
    polygon_3d: list
    base_z: float
    floor_height: float


class GeometryUploadReport(BaseModel):
    """업로드 결과 — 매칭·미매칭 집계 + 교체 여부."""

    total_units: int
    matched: int
    unmatched: int
    unmatched_samples: list[str]  # 미매칭 "동-층-호" 최대 20개
    replaced: bool


class GeometryItem(BaseModel):
    """세대 1건의 geometry + 명부 좌표(building/floor/unit)."""

    household_id: uuid.UUID
    building_name: str
    floor: int
    unit_no: int
    polygon_2d: list
    polygon_3d: list
    base_z: float
    floor_height: float
    area_m2: float | None
    unit_type_label: str | None


class GeometryListOut(BaseModel):
    items: list[GeometryItem]
    total: int


class OverlayOut(BaseModel):
    """세대 상태 오버레이 — household_id(str) → 값. occupancy는 세대원 수."""

    kind: str
    values: dict[str, float]
