"""parking — 지하주차장 배치도·차량 조회 (MANAGER, H9-5 · 점유 H16) + 입주민 주차맵(H17-2).

배치도(parking_layouts, 단지당 1행)는 렌더 페이로드를 그대로 반환하고, 차량(parking_vehicles)은
명부(households·buildings)에 **LEFT** 조인해 동·호 표시 문자열과 함께 반환한다 — 세대가 없는
외부 차량(household_id NULL)도 면을 점유하므로 목록에서 빠지면 안 된다(H16). 차량번호는 저장 시
봉투 암호화(plate_enc), 조회 시 복호해 관리자에게만 노출한다(규칙 2 — 입주민 앱·LLM 미노출).
적재는 시드 스크립트(seed_parking.py) 경로 — 이 라우터는 읽기 전용이다.
모든 쿼리는 tenant 컨텍스트 세션 + tenant_id 명시 필터로 이중 방어(규칙 3).

라우터는 둘로 나뉜다 — `router`(/admin/parking, MANAGER)는 차량번호 평문을 내보내고,
`resident_router`(/parking, RESIDENT)는 점유 여부와 본인 차량 위치만 내보낸다. 인가·응답
계약이 정반대라 한 라우터에 섞지 않는다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import PII_PLATES_VIEWED, client_ip, record_audit
from app.deps import RequestContext, get_tenant_session, require_roles
from app.pii import PiiCrypto, get_pii_crypto
from app.schemas.parking import (
    MyParkingVehicleOut,
    ParkingLayoutOut,
    ParkingMapOut,
    ParkingVehicleItem,
    ParkingVehicleListOut,
)
from liviq_db.models import Building, Household, ParkingLayout, ParkingVehicle, User

router = APIRouter(prefix="/admin/parking", tags=["parking"])
resident_router = APIRouter(prefix="/parking", tags=["parking"])

_MANAGER = require_roles("MANAGER")
_RESIDENT = require_roles("RESIDENT")
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
    request: Request,
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
) -> ParkingVehicleListOut:
    """차량 목록(동·호 오름차순, 외부 차량은 뒤). plate는 복호 평문 — 관리자 전용."""
    rows = (
        await session.execute(
            select(
                ParkingVehicle.id,
                ParkingVehicle.household_id,
                ParkingVehicle.plate_enc,
                ParkingVehicle.model,
                ParkingVehicle.is_ev,
                ParkingVehicle.spot_no,
                ParkingVehicle.entry_at,
                Building.name,
                Household.unit_no,
            )
            .outerjoin(Household, Household.id == ParkingVehicle.household_id)
            .outerjoin(Building, Building.id == Household.building_id)
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
            dong=f"{dong}동" if dong is not None else None,
            ho=f"{unit_no}호" if unit_no is not None else None,
            plate=plate_of(plate_enc),
            model=model,
            is_ev=is_ev,
            spot_no=spot_no,
            entry_at=entry_at,
            external=hid is None,
        )
        for vid, hid, plate_enc, model, is_ev, spot_no, entry_at, dong, unit_no in rows
    ]
    # 개인정보 열람 감사(docs/06 §8) — 차량번호를 **복호해 평문으로 내보내는** 유일한 경로다.
    # 번호판 자체는 기록하지 않는다(감사 로그에 개인정보 비저장 — §4.3). 건수만 남긴다.
    await record_audit(
        session,
        tenant_id=ctx.tenant_id,
        action=PII_PLATES_VIEWED,
        actor_user_id=ctx.user_id,
        meta={"count": len(vehicles)},
        ip=client_ip(request),
    )
    return ParkingVehicleListOut(vehicles=vehicles, total=len(vehicles))


# ── 입주민 주차맵 (H17-2) ─────────────────────────────────────────────────────


@resident_router.get("/map", response_model=ParkingMapOut)
async def get_parking_map(
    ctx: Annotated[RequestContext, Depends(_RESIDENT)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> ParkingMapOut:
    """배치도 + 점유 면 번호 + 본인 세대 차량 위치.

    타 세대 정보는 "면이 찼다"는 사실만 나간다 — 번호판·동호수·세대 식별자는 조회조차
    하지 않는다(규칙 2, 복호 경로 없음 → 감사 로그도 불필요). 본인 세대는 세션의
    `users.household_id`로 정하고 클라이언트 입력을 받지 않는다(규칙 4 — 우회 표면 없음).
    배치도 미적재는 404가 아니라 layout=null(관리자 /layout 과 같은 관례).
    """
    layout = await session.scalar(
        select(ParkingLayout.layout).where(ParkingLayout.tenant_id == ctx.tenant_id)
    )

    occupied = (
        await session.scalars(
            select(ParkingVehicle.spot_no)
            .where(
                ParkingVehicle.tenant_id == ctx.tenant_id,
                ParkingVehicle.spot_no.is_not(None),
            )
            .order_by(ParkingVehicle.spot_no)
        )
    ).all()

    household_id = await session.scalar(
        select(User.household_id).where(User.id == ctx.user_id, User.tenant_id == ctx.tenant_id)
    )
    # 세대 미배정(승인 전 등)은 빈 목록 — 지도 자체는 볼 수 있어야 하므로 404로 막지 않는다.
    my_rows = (
        (
            await session.execute(
                select(ParkingVehicle.spot_no, ParkingVehicle.entry_at)
                .where(
                    ParkingVehicle.tenant_id == ctx.tenant_id,
                    ParkingVehicle.household_id == household_id,
                    ParkingVehicle.spot_no.is_not(None),
                )
                .order_by(ParkingVehicle.spot_no)
            )
        ).all()
        if household_id is not None
        else []
    )

    return ParkingMapOut(
        layout=layout,
        occupied_spot_nos=[no for no in occupied if no is not None],
        my_vehicles=[
            MyParkingVehicleOut(spot_no=spot_no, entry_at=entry_at) for spot_no, entry_at in my_rows
        ],
    )
