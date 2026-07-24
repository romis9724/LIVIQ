"""twin 계약 — units.json 업로드 파싱·geometry 조회·오버레이 (H9-1, ADR-0019).

업로드는 units.json의 세대 3D 폴리곤을 명부(households) 매칭분만 적재한다(geometry만 신규,
세대·세대원은 기존 명부 재사용). 조회는 building/floor/unit을 조인해 렌더용으로 노출한다.
"""

from __future__ import annotations

import datetime
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
    """세대 상태 오버레이 — household_id(str) → 값. kind별 값 의미가 다르다(H9-2).

    occupancy=세대원 수 · inquiries=미종결 민원 수 · fees=당월 관리비(원) ·
    facilities=동 최악 설비 severity(normal 0·check 1·fault 2·risk 3).
    """

    kind: str
    values: dict[str, float]


class HouseholdMemberItem(BaseModel):
    """세대원 1건 — 실명은 마스킹만 노출(원문·생년월일 금지, 규칙 2·6)."""

    name_masked: str
    role: str
    status: str


class TwinInquiryItem(BaseModel):
    """세대 미종결 민원 1건(트윈 상세용 요약)."""

    id: uuid.UUID
    title: str
    status: str
    priority: str | None
    created_at: datetime.datetime


class TwinFeeItem(BaseModel):
    """세대 최신 월 관리비 요약."""

    period: str
    total: int


class HouseholdDetailOut(BaseModel):
    """세대 상세 — 좌표·세대원(마스킹)·미종결 민원·당월 관리비 (H9-2, MANAGER 전용)."""

    household_id: uuid.UUID
    building_name: str
    floor: int
    unit_no: int
    unit_type_label: str | None
    members: list[HouseholdMemberItem]
    open_inquiries: list[TwinInquiryItem]
    current_fee: TwinFeeItem | None
