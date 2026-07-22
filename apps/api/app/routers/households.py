"""households — 동/호수 관리 CRUD (MANAGER 전용, H8-5, docs/03 §4.1).

설정 메뉴 하위. 동(building)·세대(household)를 관리하며 세대는 층·호 범위 일괄 생성을 지원한다.
삭제 보호(CRITICAL): 세대에 입주민·명부(users)·민원(inquiries)·관리비(fees)·세대기기
(plan_devices)가 연결돼 있으면 409로 거부한다(DB FK가 최종 방어, 여기선 친화 메시지). 동은
소속 세대가 있으면 409. 모든 쿼리는 tenant 컨텍스트 세션 + tenant_id 명시 필터로 이중 방어(RLS).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_tenant_session, require_roles
from app.schemas.households import (
    BuildingCreateIn,
    BuildingItem,
    BuildingListOut,
    BuildingOut,
    BuildingUpdateIn,
    HouseholdBulkCreateIn,
    HouseholdBulkCreateOut,
    HouseholdItem,
    HouseholdListOut,
    HouseholdOut,
    HouseholdUpdateIn,
    expand_household_grid,
)
from liviq_db.models import Building, Fee, Household, Inquiry, PlanDevice, User

router = APIRouter(prefix="/admin/buildings", tags=["households"])
household_router = APIRouter(prefix="/admin/households", tags=["households"])

_MANAGER = require_roles("MANAGER")


async def _get_building(
    session: AsyncSession, tenant_id: uuid.UUID, building_id: uuid.UUID
) -> Building:
    building = await session.scalar(
        select(Building).where(Building.id == building_id, Building.tenant_id == tenant_id)
    )
    if building is None:  # 없음·타 단지(RLS 미조회) → 존재 노출 안 함
        raise HTTPException(status_code=404, detail="동을 찾을 수 없습니다")
    return building


async def _get_household(
    session: AsyncSession, tenant_id: uuid.UUID, household_id: uuid.UUID
) -> Household:
    household = await session.scalar(
        select(Household).where(Household.id == household_id, Household.tenant_id == tenant_id)
    )
    if household is None:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다")
    return household


async def _count(session: AsyncSession, model: type, **filters: object) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return int(await session.scalar(stmt) or 0)


# ── 동(building) ──────────────────────────────────────────────────────────────


@router.get("", response_model=BuildingListOut)
async def list_buildings(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> BuildingListOut:
    """동 목록 + 각 동의 세대 수(집계). 이름 오름차순."""
    buildings = list(
        await session.scalars(
            select(Building).where(Building.tenant_id == ctx.tenant_id).order_by(Building.name)
        )
    )
    count_rows = (
        await session.execute(
            select(Household.building_id, func.count())
            .where(Household.tenant_id == ctx.tenant_id)
            .group_by(Household.building_id)
        )
    ).all()
    counts: dict[uuid.UUID, int] = {building_id: count for building_id, count in count_rows}
    return BuildingListOut(
        items=[
            BuildingItem(
                id=b.id,
                name=b.name,
                floors=b.floors,
                household_count=int(counts.get(b.id, 0)),
            )
            for b in buildings
        ]
    )


@router.post("", response_model=BuildingOut, status_code=201)
async def create_building(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    body: BuildingCreateIn,
) -> BuildingOut:
    dup = await session.scalar(
        select(Building.id).where(Building.tenant_id == ctx.tenant_id, Building.name == body.name)
    )
    if dup is not None:
        raise HTTPException(status_code=409, detail="같은 이름의 동이 이미 있습니다")
    building = Building(tenant_id=ctx.tenant_id, name=body.name, floors=body.floors)
    session.add(building)
    await session.flush()
    return BuildingOut(id=building.id, name=building.name, floors=building.floors)


@router.patch("/{building_id}", response_model=BuildingOut)
async def update_building(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    building_id: uuid.UUID,
    body: BuildingUpdateIn,
) -> BuildingOut:
    building = await _get_building(session, ctx.tenant_id, building_id)
    fields = body.model_fields_set
    if "name" in fields and body.name is not None and body.name != building.name:
        dup = await session.scalar(
            select(Building.id).where(
                Building.tenant_id == ctx.tenant_id,
                Building.name == body.name,
                Building.id != building_id,
            )
        )
        if dup is not None:
            raise HTTPException(status_code=409, detail="같은 이름의 동이 이미 있습니다")
        building.name = body.name
    if "floors" in fields:
        building.floors = body.floors
    await session.flush()
    return BuildingOut(id=building.id, name=building.name, floors=building.floors)


@router.delete("/{building_id}", status_code=204)
async def delete_building(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    building_id: uuid.UUID,
) -> Response:
    """동 삭제 — 소속 세대가 있으면 409(세대를 먼저 정리해야 함)."""
    building = await _get_building(session, ctx.tenant_id, building_id)
    household_count = await _count(
        session, Household, tenant_id=ctx.tenant_id, building_id=building_id
    )
    if household_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"이 동에 세대 {household_count}개가 있어 삭제할 수 없습니다",
        )
    await session.delete(building)
    await session.flush()
    return Response(status_code=204)


# ── 세대(household) ───────────────────────────────────────────────────────────


@router.get("/{building_id}/households", response_model=HouseholdListOut)
async def list_households(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    building_id: uuid.UUID,
) -> HouseholdListOut:
    """동의 세대 목록 — 층·호 오름차순."""
    building = await _get_building(session, ctx.tenant_id, building_id)
    households = list(
        await session.scalars(
            select(Household)
            .where(
                Household.tenant_id == ctx.tenant_id,
                Household.building_id == building_id,
            )
            .order_by(Household.floor, Household.unit_no)
        )
    )
    return HouseholdListOut(
        building=BuildingOut(id=building.id, name=building.name, floors=building.floors),
        items=[
            HouseholdItem(id=h.id, floor=h.floor, unit_no=h.unit_no, status=h.status)
            for h in households
        ],
    )


@router.post("/{building_id}/households", response_model=HouseholdBulkCreateOut, status_code=201)
async def create_households(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    building_id: uuid.UUID,
    body: HouseholdBulkCreateIn,
) -> HouseholdBulkCreateOut:
    """층·호 범위 일괄 생성(단일은 start==end). 이미 있는 (층,호)는 건너뛴다(멱등)."""
    await _get_building(session, ctx.tenant_id, building_id)
    grid = expand_household_grid(body.floor_start, body.floor_end, body.unit_start, body.unit_end)
    existing = set(
        (
            await session.execute(
                select(Household.floor, Household.unit_no).where(
                    Household.tenant_id == ctx.tenant_id,
                    Household.building_id == building_id,
                )
            )
        ).all()
    )
    created = 0
    for floor, unit_no in grid:
        if (floor, unit_no) in existing:
            continue
        session.add(
            Household(
                tenant_id=ctx.tenant_id,
                building_id=building_id,
                floor=floor,
                unit_no=unit_no,
                status=body.status,
            )
        )
        created += 1
    await session.flush()
    return HouseholdBulkCreateOut(created=created, skipped=len(grid) - created)


@household_router.patch("/{household_id}", response_model=HouseholdOut)
async def update_household(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    household_id: uuid.UUID,
    body: HouseholdUpdateIn,
) -> HouseholdOut:
    """floor·unit_no·status 수정. (층,호) 변경 시 같은 동 내 중복이면 409."""
    household = await _get_household(session, ctx.tenant_id, household_id)
    fields = body.model_fields_set
    new_floor = body.floor if "floor" in fields and body.floor is not None else household.floor
    new_unit = (
        body.unit_no if "unit_no" in fields and body.unit_no is not None else household.unit_no
    )
    if (new_floor, new_unit) != (household.floor, household.unit_no):
        dup = await session.scalar(
            select(Household.id).where(
                Household.tenant_id == ctx.tenant_id,
                Household.building_id == household.building_id,
                Household.floor == new_floor,
                Household.unit_no == new_unit,
                Household.id != household_id,
            )
        )
        if dup is not None:
            raise HTTPException(status_code=409, detail="같은 동에 이미 존재하는 층·호입니다")
        household.floor = new_floor
        household.unit_no = new_unit
    if "status" in fields and body.status is not None:
        household.status = body.status
    await session.flush()
    return HouseholdOut(
        id=household.id,
        building_id=household.building_id,
        floor=household.floor,
        unit_no=household.unit_no,
        status=household.status,
    )


@household_router.delete("/{household_id}", status_code=204)
async def delete_household(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    household_id: uuid.UUID,
) -> Response:
    """세대 삭제 — 입주민·명부·민원·관리비·세대기기 연결 시 409(CRITICAL 삭제 보호)."""
    household = await _get_household(session, ctx.tenant_id, household_id)
    users = await _count(session, User, tenant_id=ctx.tenant_id, household_id=household_id)
    inquiries = await _count(session, Inquiry, tenant_id=ctx.tenant_id, household_id=household_id)
    fees = await _count(session, Fee, tenant_id=ctx.tenant_id, household_id=household_id)
    devices = await _count(session, PlanDevice, tenant_id=ctx.tenant_id, household_id=household_id)
    if users or inquiries or fees or devices:
        blockers = []
        if users:
            blockers.append(f"입주민·명부 {users}건")
        if inquiries:
            blockers.append(f"민원 {inquiries}건")
        if fees:
            blockers.append(f"관리비 {fees}건")
        if devices:
            blockers.append(f"세대기기 {devices}건")
        raise HTTPException(
            status_code=409,
            detail="연결된 데이터(" + ", ".join(blockers) + ")가 있어 세대를 삭제할 수 없습니다",
        )
    await session.delete(household)
    await session.flush()
    return Response(status_code=204)
