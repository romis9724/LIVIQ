"""twin — 단지 트윈 geometry 업로드·조회 + occupancy 오버레이 (MANAGER 전용, H9-1, ADR-0019).

geometry만 신규 — 세대·세대원은 기존 명부(households·users) 재사용. 업로드는 units.json을
파싱해 명부 매칭분만 delete-then-insert로 전체 교체하고(단일 트랜잭션), 조회는 명부 좌표를
조인해 렌더용으로 노출한다. 모든 쿼리는 tenant 컨텍스트 세션 + tenant_id 명시 필터로 이중 방어.
"""

from __future__ import annotations

import decimal
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_tenant_session, require_roles
from app.schemas.twin import (
    GeometryItem,
    GeometryListOut,
    GeometryUploadReport,
    OverlayOut,
    TwinUnitIn,
)
from liviq_db.models import Building, Household, HouseholdGeometry, User

router = APIRouter(prefix="/admin/twin", tags=["twin"])

_MANAGER = require_roles("MANAGER")

MAX_UNMATCHED_SAMPLES = 20  # 리포트에 담을 미매칭 unit 표본 상한
# occupancy 집계 대상 세대원 상태(명부·대기·정상). 탈퇴·거절·비활성은 제외.
_OCCUPANCY_STATUSES = ("pre_registered", "pending", "active")


def _normalize_building(dong: str) -> str:
    """units.json dong("401동") → buildings.name("401") — seed_households_xlsx와 동일 정규화."""
    return dong.replace("동", "").strip()


def _dec(value: float) -> decimal.Decimal:
    """float → Decimal(asyncpg는 Numeric 컬럼에 Decimal만 허용)."""
    return decimal.Decimal(str(value))


@router.get("/geometry", response_model=GeometryListOut)
async def list_geometry(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> GeometryListOut:
    """적재된 세대 geometry 목록(building/floor/unit 조인). geometry 0건이면 빈 목록."""
    rows = (
        await session.execute(
            select(
                HouseholdGeometry.household_id,
                Building.name,
                Household.floor,
                Household.unit_no,
                HouseholdGeometry.polygon_2d,
                HouseholdGeometry.polygon_3d,
                HouseholdGeometry.base_z,
                HouseholdGeometry.floor_height,
                HouseholdGeometry.area_m2,
                HouseholdGeometry.unit_type_label,
            )
            .join(Household, Household.id == HouseholdGeometry.household_id)
            .join(Building, Building.id == Household.building_id)
            .where(HouseholdGeometry.tenant_id == ctx.tenant_id)
            .order_by(Building.name, Household.floor, Household.unit_no)
        )
    ).all()
    items = [
        GeometryItem(
            household_id=hid,
            building_name=name,
            floor=floor,
            unit_no=unit_no,
            polygon_2d=poly2,
            polygon_3d=poly3,
            base_z=float(base_z),
            floor_height=float(floor_height),
            area_m2=float(area_m2) if area_m2 is not None else None,
            unit_type_label=label,
        )
        for hid, name, floor, unit_no, poly2, poly3, base_z, floor_height, area_m2, label in rows
    ]
    return GeometryListOut(items=items, total=len(items))


@router.post("/geometry", response_model=GeometryUploadReport)
async def upload_geometry(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    file: Annotated[UploadFile, File()],
) -> GeometryUploadReport:
    """units.json 업로드 → 명부 매칭분 전체 교체(delete-then-insert, 단일 트랜잭션).

    파일이 JSON 아니거나 `units` 배열이 없으면 400. 검증 실패·명부 미매칭 unit은 스킵하고
    리포트(matched/unmatched/표본)로 돌려준다.
    """
    raw = await file.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="JSON 파일이 아닙니다") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("units"), list):
        raise HTTPException(status_code=400, detail="units 배열이 없습니다")
    units = payload["units"]

    # 명부 인덱스: (building name, floor, unit_no) → household_id (해당 tenant).
    index_rows = (
        await session.execute(
            select(Building.name, Household.floor, Household.unit_no, Household.id)
            .join(Building, Building.id == Household.building_id)
            .where(Household.tenant_id == ctx.tenant_id)
        )
    ).all()
    index = {(name, floor, unit_no): hid for name, floor, unit_no, hid in index_rows}

    matched_rows: list[HouseholdGeometry] = []
    unmatched_samples: list[str] = []
    for item in units:
        try:
            unit = TwinUnitIn.model_validate(item)
        except ValidationError:
            _add_sample(unmatched_samples, item)
            continue
        household_id = index.get((_normalize_building(unit.dong), unit.floor, unit.ho))
        if household_id is None:
            _add_sample(unmatched_samples, item)
            continue
        matched_rows.append(
            HouseholdGeometry(
                tenant_id=ctx.tenant_id,
                household_id=household_id,
                polygon_2d=unit.polygon_2d,
                polygon_3d=unit.polygon_3d,
                base_z=_dec(unit.base_z),
                floor_height=_dec(unit.floor_height),
                area_m2=_dec(unit.area_m2) if unit.area_m2 is not None else None,
                unit_type_label=unit.unit_type,
            )
        )

    existing = int(
        await session.scalar(
            select(func.count())
            .select_from(HouseholdGeometry)
            .where(HouseholdGeometry.tenant_id == ctx.tenant_id)
        )
        or 0
    )
    # 전체 교체 — 재업로드 멱등(세대당 1건). get_tenant_session이 트랜잭션을 연다.
    await session.execute(
        delete(HouseholdGeometry).where(HouseholdGeometry.tenant_id == ctx.tenant_id)
    )
    session.add_all(matched_rows)
    await session.flush()

    return GeometryUploadReport(
        total_units=len(units),
        matched=len(matched_rows),
        unmatched=len(units) - len(matched_rows),
        unmatched_samples=unmatched_samples[:MAX_UNMATCHED_SAMPLES],
        replaced=existing > 0,
    )


@router.get("/overlay", response_model=OverlayOut)
async def get_overlay(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    kind: Annotated[str, Query()],
) -> OverlayOut:
    """세대 상태 오버레이. occupancy = 세대원 수(geometry 있는 세대만, 0명 세대는 생략).

    inquiries·fees·facilities 등 다른 kind는 H9-2 — 그 외 값은 400.
    """
    if kind != "occupancy":
        raise HTTPException(status_code=400, detail="지원하지 않는 오버레이 종류입니다")

    geom_households = select(HouseholdGeometry.household_id).where(
        HouseholdGeometry.tenant_id == ctx.tenant_id
    )
    rows = (
        await session.execute(
            select(User.household_id, func.count())
            .where(
                User.tenant_id == ctx.tenant_id,
                User.household_id.in_(geom_households),
                User.status.in_(_OCCUPANCY_STATUSES),
                User.deleted_at.is_(None),
            )
            .group_by(User.household_id)
        )
    ).all()
    values = {str(household_id): float(count) for household_id, count in rows}
    return OverlayOut(kind=kind, values=values)


def _add_sample(samples: list[str], item: object) -> None:
    """미매칭 unit 표본 "동-층-호" 추가(원본 필드 best-effort, 상한은 호출부에서 슬라이스)."""
    if len(samples) >= MAX_UNMATCHED_SAMPLES:
        return
    if isinstance(item, dict):
        samples.append(f"{item.get('dong')}-{item.get('floor')}-{item.get('ho')}")
    else:
        samples.append("(형식 오류)")
