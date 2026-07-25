"""parking — 지하주차장 배치도·입주민 차량 조회 (MANAGER 전용, H9-5).

배치도(parking_layouts, 단지당 1행)는 렌더 페이로드를 그대로 반환하고, 차량(parking_vehicles)은
명부(households·buildings)에 조인해 동·호 표시 문자열과 함께 반환한다. 차량번호는 저장 시
봉투 암호화(plate_enc), 조회 시 복호해 관리자에게만 노출한다(규칙 2 — 입주민 앱·LLM 미노출).
적재는 시드 스크립트(seed_parking.py) 경로 — 이 라우터는 읽기 전용이다.
모든 쿼리는 tenant 컨텍스트 세션 + tenant_id 명시 필터로 이중 방어(규칙 3).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_tenant_session, require_roles
from app.pii import PiiCrypto, get_pii_crypto
from app.schemas.parking import ParkingLayoutOut, ParkingVehicleItem, ParkingVehicleListOut
from liviq_db.models import Building, Household, ParkingLayout, ParkingVehicle

router = APIRouter(prefix="/admin/parking", tags=["parking"])

_MANAGER = require_roles("MANAGER")
_PLATE_FALLBACK = "*"  # 복호 실패 차량 — 목록엔 남기고 번호만 가린다


@router.get("/layout", response_model=ParkingLayoutOut)
async def get_layout(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> ParkingLayoutOut:
    """배치도 조회 — 미적재면 `{"layout": null}`(404 아님, 프론트가 빈 상태 렌더)."""
    layout = await session.scalar(
        select(ParkingLayout.layout).where(ParkingLayout.tenant_id == ctx.tenant_id)
    )
    return ParkingLayoutOut(layout=layout)


@router.get("/vehicles", response_model=ParkingVehicleListOut)
async def list_vehicles(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
) -> ParkingVehicleListOut:
    """입주민 차량 목록(동·호 오름차순). plate는 복호 평문 — 관리자 전용."""
    rows = (
        await session.execute(
            select(
                ParkingVehicle.id,
                ParkingVehicle.household_id,
                ParkingVehicle.plate_enc,
                ParkingVehicle.model,
                ParkingVehicle.is_ev,
                Building.name,
                Household.unit_no,
            )
            .join(Household, Household.id == ParkingVehicle.household_id)
            .join(Building, Building.id == Household.building_id)
            .where(ParkingVehicle.tenant_id == ctx.tenant_id)
            .order_by(Building.name, Household.unit_no, ParkingVehicle.created_at)
        )
    ).all()
    if not rows:
        return ParkingVehicleListOut(vehicles=[], total=0)

    dek = await crypto.get_dek(session, ctx.tenant_id)

    def plate_of(plate_enc: bytes) -> str:
        try:
            return crypto.decrypt(dek, plate_enc)
        except Exception:  # noqa: BLE001 — 복호 실패해도 목록 렌더는 중단하지 않는다
            return _PLATE_FALLBACK

    vehicles = [
        ParkingVehicleItem(
            id=vid,
            household_id=hid,
            dong=f"{dong}동",
            ho=f"{unit_no}호",
            plate=plate_of(plate_enc),
            model=model,
            is_ev=is_ev,
        )
        for vid, hid, plate_enc, model, is_ev, dong, unit_no in rows
    ]
    return ParkingVehicleListOut(vehicles=vehicles, total=len(vehicles))
