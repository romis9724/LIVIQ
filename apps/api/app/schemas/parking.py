"""parking 계약 — 지하주차장 배치도·입주민 차량 조회 (H9-5, MANAGER 전용).

배치도는 렌더 페이로드(JSONB)를 그대로 통과시킨다 — 서버는 내용을 해석하지 않는다(YAGNI).
차량은 DB엔 암호문(plate_enc)만 있고 응답의 plate는 복호 평문이다(규칙 2 — 이 라우터는
입주민 앱·LLM 미노출). dong·ho는 프로토타입 배치도와 맞춘 표시 포맷("401동"/"1502호").
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class ParkingLayoutOut(BaseModel):
    """배치도 페이로드(viewBox·buildings·boxes·cores·spots). 미적재면 null."""

    layout: dict | None


class ParkingVehicleItem(BaseModel):
    """입주민 차량 1대 — plate는 복호 평문."""

    id: uuid.UUID
    household_id: uuid.UUID
    dong: str  # 예 "401동"
    ho: str  # 예 "1502호"
    plate: str
    model: str | None
    is_ev: bool


class ParkingVehicleListOut(BaseModel):
    vehicles: list[ParkingVehicleItem]
    total: int
