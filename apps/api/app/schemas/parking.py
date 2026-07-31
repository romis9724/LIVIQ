"""parking 계약 — 지하주차장 배치도·차량 조회 (H9-5 · 점유 H16, MANAGER 전용).

배치도는 렌더 페이로드(JSONB)를 그대로 통과시킨다 — 서버는 내용을 해석하지 않는다(YAGNI).
차량은 DB엔 암호문(plate_enc)만 있고 응답의 plate는 복호 평문이다(규칙 2 — 이 라우터는
입주민 앱·LLM 미노출). dong·ho는 프로토타입 배치도와 맞춘 표시 포맷("401동"/"1502호")이며
외부 차량(external)은 세대가 없어 셋 다 null이다. spot_no·entry_at은 DB가 단일 출처인
점유 상태 — 프론트는 이 값으로 배치도를 칠한다(H16, 시뮬레이션 폐기).
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel


class ParkingLayoutOut(BaseModel):
    """배치도 페이로드(viewBox·buildings·boxes·cores·spots). 미적재면 null."""

    layout: dict | None


class ParkingVehicleItem(BaseModel):
    """차량 1대 — plate는 복호 평문. 외부 차량은 household_id·dong·ho가 null."""

    id: uuid.UUID
    household_id: uuid.UUID | None
    dong: str | None  # 예 "401동"
    ho: str | None  # 예 "1502호"
    plate: str
    model: str | None
    is_ev: bool
    spot_no: str | None  # 주차 중인 면 번호(layout spots.no) — null이면 미주차
    entry_at: datetime.datetime | None
    external: bool  # 명부에 없는 외부 차량(household_id NULL)


class ParkingVehicleListOut(BaseModel):
    vehicles: list[ParkingVehicleItem]
    total: int
