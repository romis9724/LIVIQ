"""평면도 계약 — 입주민 본인 세대 평면도 조회 (docs/01 §13, docs/03 §4.8, H13-3)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

__all__ = ["FloorPlanOut", "MyFloorPlanOut", "PlanDeviceOut"]


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
