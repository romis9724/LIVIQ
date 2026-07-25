"""parking — 주차장 대시보드 CRUD (MANAGER 전용, H9-5).

세대에 배정된 주차면(위치·차량번호 선택, 세대당 다건)을 관리한다. 대시보드는 배정 행을 명부
(households·buildings)에 조인해 세대 단위로 묶고 현황을 집계한다. 차량번호는 저장 시 봉투
암호화(plate_enc), 조회 시 복호해 관리자에게만 노출한다(규칙 2 — 입주민 앱·LLM 미노출).
모든 쿼리는 tenant 컨텍스트 세션 + tenant_id 명시 필터로 이중 방어(규칙 3).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_tenant_session, require_roles
from app.pii import PiiCrypto, get_pii_crypto
from app.schemas.parking import (
    ParkingAssignmentIn,
    ParkingAssignmentItem,
    ParkingAssignmentOut,
    ParkingAssignmentUpdateIn,
    ParkingDashboardOut,
    ParkingHouseholdItem,
    ParkingSummary,
)
from liviq_db.models import Building, Household, ParkingAssignment

router = APIRouter(prefix="/admin/parking", tags=["parking"])

_MANAGER = require_roles("MANAGER")


async def _require_household(
    session: AsyncSession, tenant_id: uuid.UUID, household_id: uuid.UUID
) -> None:
    """household_id가 이 단지 세대인지 검증 — 아니면 404(존재 노출 안 함)."""
    exists = await session.scalar(
        select(Household.id).where(Household.tenant_id == tenant_id, Household.id == household_id)
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다")


async def _get_assignment(
    session: AsyncSession, tenant_id: uuid.UUID, assignment_id: uuid.UUID
) -> ParkingAssignment:
    row = await session.scalar(
        select(ParkingAssignment).where(
            ParkingAssignment.tenant_id == tenant_id, ParkingAssignment.id == assignment_id
        )
    )
    if row is None:  # 없음·타 단지(RLS 미조회) → 존재 노출 안 함
        raise HTTPException(status_code=404, detail="주차 배정을 찾을 수 없습니다")
    return row


async def _encrypt_plate(
    session: AsyncSession, crypto: PiiCrypto, tenant_id: uuid.UUID, plate: str | None
) -> bytes | None:
    """차량번호 평문 → 암호문(빈 값이면 None으로 클리어). 평문은 DB에 저장하지 않는다."""
    if not plate:
        return None
    dek = await crypto.get_dek(session, tenant_id)
    return crypto.encrypt(dek, plate)


def _decrypt_plate(crypto: PiiCrypto, dek: bytes | None, plate_enc: bytes | None) -> str | None:
    """암호문 → 평문(없거나 복호 실패면 None — 대시보드는 값만 숨기고 계속)."""
    if plate_enc is None or dek is None:
        return None
    try:
        return crypto.decrypt(dek, plate_enc)
    except Exception:  # noqa: BLE001 — 복호 실패해도 대시보드 렌더는 중단하지 않는다
        return None


@router.get("", response_model=ParkingDashboardOut)
async def get_dashboard(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
) -> ParkingDashboardOut:
    """주차 현황 요약 + 배정된 세대 목록(배정 1건 이상인 세대만). 동·층·호 오름차순."""
    rows = (
        await session.execute(
            select(
                ParkingAssignment.id,
                ParkingAssignment.household_id,
                ParkingAssignment.location_code,
                ParkingAssignment.plate_enc,
                Building.name,
                Household.floor,
                Household.unit_no,
            )
            .join(Household, Household.id == ParkingAssignment.household_id)
            .join(Building, Building.id == Household.building_id)
            .where(ParkingAssignment.tenant_id == ctx.tenant_id)
            .order_by(
                Building.name,
                Household.floor,
                Household.unit_no,
                ParkingAssignment.created_at,
            )
        )
    ).all()

    dek = await crypto.get_dek(session, ctx.tenant_id) if rows else None
    total_vehicles = 0
    # rows가 정렬돼 있으므로 dict 삽입 순서 = 표시 순서(세대 단위 그룹핑).
    groups: dict[uuid.UUID, dict] = {}
    for aid, hid, location_code, plate_enc, dong, floor, ho in rows:
        has_vehicle = plate_enc is not None
        if has_vehicle:
            total_vehicles += 1
        group = groups.get(hid)
        if group is None:
            group = {
                "dong": dong,
                "floor": floor,
                "ho": ho,
                "vehicle_count": 0,
                "assignments": [],
            }
            groups[hid] = group
        group["assignments"].append(
            ParkingAssignmentItem(
                id=aid,
                location_code=location_code,
                plate=_decrypt_plate(crypto, dek, plate_enc),
            )
        )
        if has_vehicle:
            group["vehicle_count"] += 1

    households = [
        ParkingHouseholdItem(
            household_id=hid,
            dong=group["dong"],
            floor=group["floor"],
            ho=group["ho"],
            unit_label=f"{group['dong']}동 {group['ho']}호",
            space_count=len(group["assignments"]),
            vehicle_count=group["vehicle_count"],
            assignments=group["assignments"],
        )
        for hid, group in groups.items()
    ]

    total_households = int(
        await session.scalar(
            select(func.count()).select_from(Household).where(Household.tenant_id == ctx.tenant_id)
        )
        or 0
    )
    assigned = len(groups)
    return ParkingDashboardOut(
        summary=ParkingSummary(
            total_spaces=len(rows),
            total_vehicles=total_vehicles,
            assigned_households=assigned,
            unassigned_households=max(total_households - assigned, 0),
        ),
        households=households,
    )


@router.post("", response_model=ParkingAssignmentOut, status_code=201)
async def create_assignment(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    body: ParkingAssignmentIn,
) -> ParkingAssignmentOut:
    """주차면 배정 생성 — household_id가 이 단지 세대여야 한다(아니면 404)."""
    await _require_household(session, ctx.tenant_id, body.household_id)
    plate = body.plate or None
    row = ParkingAssignment(
        tenant_id=ctx.tenant_id,
        household_id=body.household_id,
        location_code=body.location_code or None,
        plate_enc=await _encrypt_plate(session, crypto, ctx.tenant_id, plate),
    )
    session.add(row)
    await session.flush()
    return ParkingAssignmentOut(
        id=row.id,
        household_id=row.household_id,
        location_code=row.location_code,
        plate=plate,
    )


@router.patch("/{assignment_id}", response_model=ParkingAssignmentOut)
async def update_assignment(
    assignment_id: uuid.UUID,
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    body: ParkingAssignmentUpdateIn,
) -> ParkingAssignmentOut:
    """위치·차량번호 전체 교체(빈 값/null이면 클리어, 값 있으면 재암호화)."""
    row = await _get_assignment(session, ctx.tenant_id, assignment_id)
    plate = body.plate or None
    row.location_code = body.location_code or None
    row.plate_enc = await _encrypt_plate(session, crypto, ctx.tenant_id, plate)
    await session.flush()
    return ParkingAssignmentOut(
        id=row.id,
        household_id=row.household_id,
        location_code=row.location_code,
        plate=plate,
    )


@router.delete("/{assignment_id}", status_code=204)
async def delete_assignment(
    assignment_id: uuid.UUID,
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> Response:
    """주차면 배정 삭제(leaf — FK 의존자 없음)."""
    row = await _get_assignment(session, ctx.tenant_id, assignment_id)
    await session.delete(row)
    await session.flush()
    return Response(status_code=204)
