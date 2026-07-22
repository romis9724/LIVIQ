"""동/호수 관리 계약 — /admin/buildings·/admin/households (H8-5, docs/03 §4.1).

동(building)은 이름·층수(마스터), 세대(household)는 동·층·호로 구조화된다. 세대는 단일 생성뿐
아니라 층·호 범위 일괄 생성을 지원한다(예: 1~15층 × 1~2호 = 30세대). 범위 조합 폭발을 막기
위해 상한을 둔다(BULK_MAX_HOUSEHOLDS). 삭제 보호(입주민·명부·민원·관리비 연결)는 라우터가 소유.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, model_validator

# 일괄 생성 1회 조합 상한 — 실수/악용 방지(초대량은 seed_households_xlsx.py 스크립트 경로).
BULK_MAX_HOUSEHOLDS = 2000
# 세대 상태 — 기본 active(입주 가능). inactive는 공실·사용 중지 표시(집계·필터용).
HOUSEHOLD_STATUSES = ("active", "inactive")
BUILDING_MAX_FLOORS = 200

__all__ = [
    "BUILDING_MAX_FLOORS",
    "BULK_MAX_HOUSEHOLDS",
    "BuildingCreateIn",
    "BuildingItem",
    "BuildingListOut",
    "BuildingOut",
    "BuildingUpdateIn",
    "HouseholdBulkCreateIn",
    "HouseholdBulkCreateOut",
    "HouseholdItem",
    "HouseholdListOut",
    "HouseholdOut",
    "HouseholdUpdateIn",
    "expand_household_grid",
]


class BuildingOut(BaseModel):
    id: uuid.UUID
    name: str
    floors: int | None


class BuildingItem(BuildingOut):
    household_count: int = 0


class BuildingListOut(BaseModel):
    items: list[BuildingItem]


class BuildingCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    floors: int | None = Field(default=None, ge=1, le=BUILDING_MAX_FLOORS)


class BuildingUpdateIn(BaseModel):
    """name·floors만 수정 — 전달한 필드만 반영(model_fields_set)."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    floors: int | None = Field(default=None, ge=1, le=BUILDING_MAX_FLOORS)


class HouseholdOut(BaseModel):
    id: uuid.UUID
    building_id: uuid.UUID
    floor: int
    unit_no: int
    status: str


class HouseholdItem(BaseModel):
    id: uuid.UUID
    floor: int
    unit_no: int
    status: str


class HouseholdListOut(BaseModel):
    building: BuildingOut
    items: list[HouseholdItem]


class HouseholdBulkCreateIn(BaseModel):
    """층·호 범위 일괄 생성. 단일 세대는 start==end로 지정한다.

    floor_start~floor_end × unit_start~unit_end의 데카르트 곱을 세대로 만든다. 이미 있는
    (층,호)는 건너뛴다(멱등). 상한 초과·역순 범위는 422.
    """

    floor_start: int = Field(ge=-10, le=BUILDING_MAX_FLOORS)
    floor_end: int = Field(ge=-10, le=BUILDING_MAX_FLOORS)
    unit_start: int = Field(ge=1, le=99)
    unit_end: int = Field(ge=1, le=99)
    status: str = Field(default="active")

    @model_validator(mode="after")
    def _check_ranges(self) -> HouseholdBulkCreateIn:
        if self.floor_end < self.floor_start:
            raise ValueError("floor_end는 floor_start 이상이어야 합니다")
        if self.unit_end < self.unit_start:
            raise ValueError("unit_end는 unit_start 이상이어야 합니다")
        if self.status not in HOUSEHOLD_STATUSES:
            raise ValueError(f"status는 {HOUSEHOLD_STATUSES} 중 하나여야 합니다")
        total = (self.floor_end - self.floor_start + 1) * (self.unit_end - self.unit_start + 1)
        if total > BULK_MAX_HOUSEHOLDS:
            raise ValueError(f"1회 최대 {BULK_MAX_HOUSEHOLDS}세대까지 생성할 수 있습니다")
        return self


class HouseholdBulkCreateOut(BaseModel):
    created: int
    skipped: int  # 이미 존재해 건너뛴 (층,호) 수


class HouseholdUpdateIn(BaseModel):
    """floor·unit_no·status 수정 — 전달한 필드만 반영."""

    floor: int | None = Field(default=None, ge=-10, le=BUILDING_MAX_FLOORS)
    unit_no: int | None = Field(default=None, ge=1, le=99)
    status: str | None = None


def expand_household_grid(
    floor_start: int, floor_end: int, unit_start: int, unit_end: int
) -> list[tuple[int, int]]:
    """층·호 범위 → (층, 호) 조합 목록(층 오름차순, 그 안에서 호 오름차순).

    범위 정합성(end>=start)은 HouseholdBulkCreateIn이 이미 검증했다고 가정한다.
    """
    return [
        (floor, unit)
        for floor in range(floor_start, floor_end + 1)
        for unit in range(unit_start, unit_end + 1)
    ]
