"""parking 계약 — 주차장 대시보드 CRUD (H9-5, MANAGER 전용).

1행 = 배정 주차면 1개(위치·차량번호 선택, 세대당 다건). plate는 관리자와 평문으로 오가되 DB엔
암호화 저장한다(규칙 2 — 이 라우터는 입주민 앱·LLM 미노출). 형식 검증은 하지 않고 길이만 제한.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class ParkingAssignmentIn(BaseModel):
    """주차면 생성 입력 — household_id + 위치·차량번호(선택)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    household_id: uuid.UUID
    location_code: str | None = Field(default=None, max_length=40)
    plate: str | None = Field(default=None, max_length=20)


class ParkingAssignmentUpdateIn(BaseModel):
    """주차면 수정 입력 — 위치·차량번호 전체 교체(빈 값/null이면 클리어)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    location_code: str | None = Field(default=None, max_length=40)
    plate: str | None = Field(default=None, max_length=20)


class ParkingAssignmentOut(BaseModel):
    """주차면 1건 — plate는 복호 평문."""

    id: uuid.UUID
    household_id: uuid.UUID
    location_code: str | None
    plate: str | None


class ParkingAssignmentItem(BaseModel):
    """대시보드 세대 행의 배정 1건(plate=복호 평문)."""

    id: uuid.UUID
    location_code: str | None
    plate: str | None


class ParkingHouseholdItem(BaseModel):
    """대시보드 세대 행 — 배정 1건 이상인 세대만."""

    household_id: uuid.UUID
    dong: str
    floor: int
    ho: int
    unit_label: str  # 예 "401동 1502호"
    space_count: int
    vehicle_count: int
    assignments: list[ParkingAssignmentItem]


class ParkingSummary(BaseModel):
    """주차 현황 요약 타일."""

    total_spaces: int
    total_vehicles: int
    assigned_households: int
    unassigned_households: int


class ParkingDashboardOut(BaseModel):
    """주차장 대시보드 페이로드 — 요약 + 배정된 세대 목록."""

    summary: ParkingSummary
    households: list[ParkingHouseholdItem]
