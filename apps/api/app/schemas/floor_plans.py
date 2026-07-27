"""평면도 계약 — 입주민 본인 세대 평면도 조회(H13-3) + 관리자 편집(H13-4, docs/01 §13,
docs/03 §4.8)."""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "MAX_PLAN_DEVICES",
    "AdminFloorPlanDetailOut",
    "AdminFloorPlanListItemOut",
    "AdminFloorPlanListOut",
    "AdminPlanDeviceIn",
    "AdminPlanDevicesReplaceIn",
    "FloorPlanOut",
    "MyFloorPlanOut",
    "PlanDeviceOut",
]

MAX_PLAN_DEVICES = 500  # 도면 1건당 장치 상한(무한 업로드 방지)
_Dir = Literal["up", "down", "left", "right"]


class FloorPlanOut(BaseModel):
    """세대타입 평면도 배경 이미지 — image_url은 서명 URL(TTL 10분, docs/06 §5)."""

    id: uuid.UUID
    image_url: str
    image_width: int | None
    image_height: int | None
    unit_type_name: str


class PlanDeviceOut(BaseModel):
    """장치/방 마커 1건 — device_type='room'은 방 중심좌표(§4.8 방 중심좌표 문단)."""

    id: uuid.UUID
    device_type: str
    x: float
    y: float
    room: str | None
    dir: str | None
    label: str | None
    memo: str | None
    facility_id: uuid.UUID | None


class MyFloorPlanOut(BaseModel):
    plan: FloorPlanOut
    devices: list[PlanDeviceOut]


class AdminFloorPlanListItemOut(BaseModel):
    """관리자 평면도 목록 1건 — unit_type당 1행."""

    id: uuid.UUID
    unit_type_name: str
    image_url: str
    image_width: int | None
    image_height: int | None
    device_count: int
    updated_at: datetime.datetime


class AdminFloorPlanListOut(BaseModel):
    items: list[AdminFloorPlanListItemOut]


class AdminFloorPlanDetailOut(BaseModel):
    """관리자 도면 1건 상세 — devices는 PUT이 교체하는 것과 동일 범위(action=base)."""

    plan: FloorPlanOut
    devices: list[PlanDeviceOut]


class AdminPlanDeviceIn(BaseModel):
    """장치 전체교체 입력 1건 — action='base'·household_id=NULL 고정(오버라이드 미구현)."""

    device_type: str = Field(min_length=1, max_length=50)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    room: str | None = None
    dir: _Dir | None = None
    label: str | None = Field(default=None, max_length=200)
    memo: str | None = Field(default=None, max_length=2000)
    facility_id: uuid.UUID | None = None


class AdminPlanDevicesReplaceIn(BaseModel):
    devices: list[AdminPlanDeviceIn] = Field(max_length=MAX_PLAN_DEVICES)
