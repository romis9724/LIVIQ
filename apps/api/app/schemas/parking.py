"""parking 계약 — 지하주차장 배치도·차량 조회 (H9-5 · 점유 H16) + 입주민 주차맵(H17-2).

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


# ── 입주민 주차맵 (H17-2) ─────────────────────────────────────────────────────
# 관리자 계약과 **다른 모델**을 쓴다. 입주민에겐 타 세대 차량의 번호판·동호수는 물론
# 세대 식별자·소속(입주민/외부) 구분도 주지 않는다(규칙 2) — 필드 자체를 두지 않아
# 실수로 채워질 여지를 없앤다. 노출은 "그 면이 찼는가"와 "내 차가 어디 있는가"뿐이다.


class MyParkingVehicleOut(BaseModel):
    """본인 세대 차량 중 **주차 중인** 1대. 번호판은 넣지 않는다(복호할 이유가 없다)."""

    spot_no: str
    entry_at: datetime.datetime | None


class ParkingMapOut(BaseModel):
    """배치도 + 점유 면 번호 + 본인 세대 차량 위치. 배치도 미적재면 layout=null."""

    layout: dict | None
    occupied_spot_nos: list[str]
    my_vehicles: list[MyParkingVehicleOut]
