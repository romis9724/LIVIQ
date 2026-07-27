"""floor_plans — 입주민 본인 세대 평면도 조회 (RESIDENT 전용, H13-3, docs/03 §4.8).

세션 household_id로 직행(동·호 선택 없음, 파라미터로 household/plan id를 받지 않아 우회
표면 자체가 없다 — 소유권은 항상 세션 기준). 흐름: household → household_geometries의
unit_type_label(트윈 업로드 원본 라벨) → 라벨 정규화(괄호 이하 제거) → unit_types.name
매칭 → 해당 타입 floor_plans(scope=unit_type) 1건 + plan_devices(action=base) 전부.
세대 없음·geometry 없음·라벨 매칭 실패·도면 없음은 전부 404(§4.8 접근 통제 — 앱 소유권
검증, RLS는 tenant 경계까지만).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, Storage, get_storage, get_tenant_session, require_roles
from app.schemas.floor_plans import FloorPlanOut, MyFloorPlanOut, PlanDeviceOut
from liviq_db.models import FloorPlan, HouseholdGeometry, PlanDevice, UnitType, User

router = APIRouter(tags=["floor-plans"])

_RESIDENT = require_roles("RESIDENT")


def _normalize_label(label: str) -> str:
    """업로드 원본 라벨("84M(공공임대)") → 마스터 매칭용("84M") — 괄호 이하·공백 제거."""
    return label.split("(", 1)[0].strip()


async def _resident_household_id(session: AsyncSession, ctx: RequestContext) -> uuid.UUID:
    household_id = await session.scalar(
        select(User.household_id).where(User.id == ctx.user_id, User.tenant_id == ctx.tenant_id)
    )
    if household_id is None:
        raise HTTPException(status_code=404, detail="세대가 배정되지 않았습니다")
    return household_id


@router.get("/me/floor-plan", response_model=MyFloorPlanOut)
async def get_my_floor_plan(
    ctx: Annotated[RequestContext, Depends(_RESIDENT)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> MyFloorPlanOut:
    household_id = await _resident_household_id(session, ctx)

    unit_type_label = await session.scalar(
        select(HouseholdGeometry.unit_type_label).where(
            HouseholdGeometry.tenant_id == ctx.tenant_id,
            HouseholdGeometry.household_id == household_id,
        )
    )
    if not unit_type_label:
        raise HTTPException(status_code=404, detail="세대 평형 정보가 없습니다")

    unit_type = await session.scalar(
        select(UnitType).where(
            UnitType.tenant_id == ctx.tenant_id,
            UnitType.name == _normalize_label(unit_type_label),
        )
    )
    if unit_type is None:
        raise HTTPException(status_code=404, detail="일치하는 평면도 타입을 찾을 수 없습니다")

    plan = await session.scalar(
        select(FloorPlan).where(
            FloorPlan.tenant_id == ctx.tenant_id,
            FloorPlan.scope == "unit_type",
            FloorPlan.unit_type_id == unit_type.id,
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="등록된 평면도가 없습니다")

    devices = await session.scalars(
        select(PlanDevice)
        .where(
            PlanDevice.tenant_id == ctx.tenant_id,
            PlanDevice.floor_plan_id == plan.id,
            PlanDevice.household_id.is_(None),
            PlanDevice.action == "base",
        )
        .order_by(PlanDevice.created_at)
    )

    image_url = await storage.presigned_get_url(plan.image_key)
    return MyFloorPlanOut(
        plan=FloorPlanOut(
            id=plan.id,
            image_url=image_url,
            image_width=plan.image_width,
            image_height=plan.image_height,
            unit_type_name=unit_type.name,
        ),
        devices=[
            PlanDeviceOut(
                id=d.id,
                device_type=d.device_type,
                x=float(d.x),
                y=float(d.y),
                room=d.room,
                dir=d.dir,
                label=d.label,
                memo=d.memo,
                facility_id=d.facility_id,
            )
            for d in devices
        ],
    )
