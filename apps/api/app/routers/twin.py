"""twin — 단지 트윈 geometry 업로드·조회 + occupancy 오버레이 (MANAGER 전용, H9-1, ADR-0019).

geometry만 신규 — 세대·세대원은 기존 명부(households·users) 재사용. 업로드는 units.json을
파싱해 명부 매칭분만 delete-then-insert로 전체 교체하고(단일 트랜잭션), 조회는 명부 좌표를
조인해 렌더용으로 노출한다. 모든 쿼리는 tenant 컨텍스트 세션 + tenant_id 명시 필터로 이중 방어.
"""

from __future__ import annotations

import decimal
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_tenant_session, require_roles
from app.pii import PiiCrypto, get_pii_crypto
from app.routers.approvals import mask_name
from app.schemas.twin import (
    GeometryItem,
    GeometryListOut,
    GeometryUploadReport,
    HouseholdDetailOut,
    HouseholdMemberItem,
    OverlayOut,
    TwinFeeItem,
    TwinInquiryItem,
    TwinUnitIn,
)
from liviq_db.models import (
    Building,
    Facility,
    Fee,
    Household,
    HouseholdGeometry,
    Inquiry,
    PiiVault,
    User,
    UserRole,
)

router = APIRouter(prefix="/admin/twin", tags=["twin"])

_MANAGER = require_roles("MANAGER")

MAX_UNMATCHED_SAMPLES = 20  # 리포트에 담을 미매칭 unit 표본 상한
# occupancy·세대원 집계 대상 상태(명부·대기·정상). 탈퇴·거절·비활성은 제외.
_OCCUPANCY_STATUSES = ("pre_registered", "pending", "active")
# 미종결 = 이 밖의 상태(received·assigned·in_progress·reopened 등).
_CLOSED_INQUIRY_STATUSES = ("done",)
_SEVERITY = {"normal": 0.0, "check": 1.0, "fault": 2.0, "risk": 3.0}  # 설비 상태 → 오버레이 값


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
    """세대 상태 오버레이 — household_id → 값. 모든 kind가 geometry 있는 세대만 스코프.

    occupancy=세대원 수 · inquiries=미종결 민원 수 · fees=당월 관리비 ·
    facilities=동 최악 설비 severity. 값 없는 세대는 키 생략(0으로 채우지 않음). 그 외 400.
    """
    if kind == "occupancy":
        values = await _overlay_occupancy(session, ctx.tenant_id)
    elif kind == "inquiries":
        values = await _overlay_inquiries(session, ctx.tenant_id)
    elif kind == "fees":
        values = await _overlay_fees(session, ctx.tenant_id)
    elif kind == "facilities":
        values = await _overlay_facilities(session, ctx.tenant_id)
    else:
        raise HTTPException(status_code=400, detail="지원하지 않는 오버레이 종류입니다")
    return OverlayOut(kind=kind, values=values)


def _geom_household_ids(tenant_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """geometry 보유 세대 id 서브쿼리 — 모든 오버레이의 공통 스코프."""
    return select(HouseholdGeometry.household_id).where(HouseholdGeometry.tenant_id == tenant_id)


async def _overlay_occupancy(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, float]:
    """세대원 수(집계 대상 상태·비삭제). 0명 세대는 생략."""
    rows = (
        await session.execute(
            select(User.household_id, func.count())
            .where(
                User.tenant_id == tenant_id,
                User.household_id.in_(_geom_household_ids(tenant_id)),
                User.status.in_(_OCCUPANCY_STATUSES),
                User.deleted_at.is_(None),
            )
            .group_by(User.household_id)
        )
    ).all()
    return {str(household_id): float(count) for household_id, count in rows}


async def _overlay_inquiries(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, float]:
    """세대별 미종결 민원 수(status NOT IN done, 비삭제). 0건 세대는 생략."""
    rows = (
        await session.execute(
            select(Inquiry.household_id, func.count())
            .where(
                Inquiry.tenant_id == tenant_id,
                Inquiry.household_id.in_(_geom_household_ids(tenant_id)),
                Inquiry.status.not_in(_CLOSED_INQUIRY_STATUSES),
                Inquiry.deleted_at.is_(None),
            )
            .group_by(Inquiry.household_id)
        )
    ).all()
    return {str(household_id): float(count) for household_id, count in rows}


async def _overlay_fees(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, float]:
    """세대별 당월(최신 period) 관리비 총액. fees 없으면 빈 맵."""
    latest = await session.scalar(select(func.max(Fee.period)).where(Fee.tenant_id == tenant_id))
    if latest is None:
        return {}
    rows = (
        await session.execute(
            select(Fee.household_id, Fee.total_amount).where(
                Fee.tenant_id == tenant_id,
                Fee.period == latest,
                Fee.household_id.in_(_geom_household_ids(tenant_id)),
            )
        )
    ).all()
    return {str(hid): float(total) for hid, total in rows if total is not None}


async def _overlay_facilities(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, float]:
    """동 단위 설비 severity 오버레이.

    한계(best-effort): facility.location 문자열을 building.name과 매칭(정확·'N동'·부분포함)해
    각 동의 최악 상태 severity를 그 동 소속 세대(geometry 보유)에 부여한다. location이
    공용/미매칭인 설비는 동 단위가 아니므로 세대 오버레이에서 제외한다. 매칭 설비 없는 동의
    세대는 생략(0으로 채우지 않음).
    """
    geom_rows = (
        await session.execute(
            select(HouseholdGeometry.household_id, Building.name)
            .join(Household, Household.id == HouseholdGeometry.household_id)
            .join(Building, Building.id == Household.building_id)
            .where(HouseholdGeometry.tenant_id == tenant_id)
        )
    ).all()
    if not geom_rows:
        return {}
    facilities = [
        (location, status)
        for location, status in (
            await session.execute(
                select(Facility.location, Facility.status).where(
                    Facility.tenant_id == tenant_id, Facility.deleted_at.is_(None)
                )
            )
        ).all()
    ]
    worst = {
        name: sev
        for name in {name for _, name in geom_rows}
        if (sev := _building_severity(name, facilities)) is not None
    }
    return {str(hid): worst[name] for hid, name in geom_rows if name in worst}


def _building_severity(
    building_name: str, facilities: list[tuple[str | None, str]]
) -> float | None:
    """동에 매칭되는 설비들의 최악 severity(없으면 None)."""
    best: float | None = None
    for location, status in facilities:
        if location and _location_matches(location, building_name):
            sev = _SEVERITY.get(status)
            if sev is not None and (best is None or sev > best):
                best = sev
    return best


def _location_matches(location: str, building_name: str) -> bool:
    """설비 location이 동 이름과 매칭되는지(정확·'N동'·부분포함, best-effort)."""
    return (
        location == building_name or location == f"{building_name}동" or building_name in location
    )


@router.get("/households/{household_id}", response_model=HouseholdDetailOut)
async def get_household_detail(
    household_id: uuid.UUID,
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
) -> HouseholdDetailOut:
    """세대 상세 — 좌표·세대원(마스킹)·미종결 민원·당월 관리비.

    tenant 격리(CRITICAL): 타 단지 household_id는 404(존재조차 노출하지 않음). 세대원 실명은
    마스킹만 노출한다(원문·생년월일 금지 — 규칙 2·6, 트윈은 관리자 화면이나 최소 노출).
    """
    row = (
        await session.execute(
            select(
                Building.name,
                Household.floor,
                Household.unit_no,
                HouseholdGeometry.unit_type_label,
            )
            .join(Building, Building.id == Household.building_id)
            .outerjoin(HouseholdGeometry, HouseholdGeometry.household_id == Household.id)
            .where(Household.tenant_id == ctx.tenant_id, Household.id == household_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다")
    building_name, floor, unit_no, unit_type_label = row

    members = await _household_members(session, crypto, ctx.tenant_id, household_id)
    open_inquiries = await _household_open_inquiries(session, ctx.tenant_id, household_id)
    current_fee = await _household_current_fee(session, ctx.tenant_id, household_id)
    return HouseholdDetailOut(
        household_id=household_id,
        building_name=building_name,
        floor=floor,
        unit_no=unit_no,
        unit_type_label=unit_type_label,
        members=members,
        open_inquiries=open_inquiries,
        current_fee=current_fee,
    )


async def _household_members(
    session: AsyncSession, crypto: PiiCrypto, tenant_id: uuid.UUID, household_id: uuid.UUID
) -> list[HouseholdMemberItem]:
    """세대원(집계 대상 상태·비삭제) — 실명 마스킹 + 첫 역할(없으면 RESIDENT)."""
    rows = (
        await session.execute(
            select(User.id, PiiVault.name_enc, User.status)
            .outerjoin(PiiVault, PiiVault.id == User.pii_ref)
            .where(
                User.tenant_id == tenant_id,
                User.household_id == household_id,
                User.status.in_(_OCCUPANCY_STATUSES),
                User.deleted_at.is_(None),
            )
        )
    ).all()
    if not rows:
        return []
    role_map = await _role_map(session, tenant_id, [uid for uid, _, _ in rows])
    dek = await crypto.get_dek(session, tenant_id)

    def masked(name_enc: bytes | None) -> str:
        if name_enc is None:
            return "*"
        try:
            return mask_name(crypto.decrypt(dek, name_enc))
        except Exception:  # noqa: BLE001 — 복호 실패 세대원도 목록엔 남긴다
            return "*"

    return [
        HouseholdMemberItem(
            name_masked=masked(name_enc), role=role_map.get(uid, "RESIDENT"), status=status
        )
        for uid, name_enc, status in rows
    ]


async def _role_map(
    session: AsyncSession, tenant_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """user_id → 첫 역할(정렬 안정성 위해 role asc)."""
    rows = (
        await session.execute(
            select(UserRole.user_id, UserRole.role)
            .where(UserRole.tenant_id == tenant_id, UserRole.user_id.in_(user_ids))
            .order_by(UserRole.user_id, UserRole.role)
        )
    ).all()
    result: dict[uuid.UUID, str] = {}
    for uid, role in rows:
        result.setdefault(uid, role)
    return result


async def _household_open_inquiries(
    session: AsyncSession, tenant_id: uuid.UUID, household_id: uuid.UUID
) -> list[TwinInquiryItem]:
    """세대 미종결 민원(최신순)."""
    rows = (
        await session.execute(
            select(Inquiry.id, Inquiry.title, Inquiry.status, Inquiry.priority, Inquiry.created_at)
            .where(
                Inquiry.tenant_id == tenant_id,
                Inquiry.household_id == household_id,
                Inquiry.status.not_in(_CLOSED_INQUIRY_STATUSES),
                Inquiry.deleted_at.is_(None),
            )
            .order_by(Inquiry.created_at.desc())
        )
    ).all()
    return [
        TwinInquiryItem(id=iid, title=title, status=status, priority=priority, created_at=created)
        for iid, title, status, priority, created in rows
    ]


async def _household_current_fee(
    session: AsyncSession, tenant_id: uuid.UUID, household_id: uuid.UUID
) -> TwinFeeItem | None:
    """세대 최신 period 관리비 요약(없으면 None)."""
    latest = await session.scalar(
        select(func.max(Fee.period)).where(
            Fee.tenant_id == tenant_id, Fee.household_id == household_id
        )
    )
    if latest is None:
        return None
    total = await session.scalar(
        select(Fee.total_amount).where(
            Fee.tenant_id == tenant_id,
            Fee.household_id == household_id,
            Fee.period == latest,
        )
    )
    return TwinFeeItem(period=latest, total=int(total) if total is not None else 0)


def _add_sample(samples: list[str], item: object) -> None:
    """미매칭 unit 표본 "동-층-호" 추가(원본 필드 best-effort, 상한은 호출부에서 슬라이스)."""
    if len(samples) >= MAX_UNMATCHED_SAMPLES:
        return
    if isinstance(item, dict):
        samples.append(f"{item.get('dong')}-{item.get('floor')}-{item.get('ho')}")
    else:
        samples.append("(형식 오류)")
