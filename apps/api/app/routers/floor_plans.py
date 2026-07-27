"""floor_plans — 입주민 본인 세대 평면도 조회(RESIDENT, H13-3) + 관리자 평면도 편집
(MANAGER, H13-4, docs/03 §4.8).

## 입주민(§/me/floor-plan)
세션 household_id로 직행(동·호 선택 없음, 파라미터로 household/plan id를 받지 않아 우회
표면 자체가 없다 — 소유권은 항상 세션 기준). 흐름: household → household_geometries의
unit_type_label(트윈 업로드 원본 라벨) → 라벨 정규화(괄호 이하 제거) → unit_types.name
매칭 → 해당 타입 floor_plans(scope=unit_type) 1건 + plan_devices(action=base) 전부.
세대 없음·geometry 없음·라벨 매칭 실패·도면 없음은 전부 404(§4.8 접근 통제 — 앱 소유권
검증, RLS는 tenant 경계까지만).

## 관리자(/admin/floor-plans, MANAGER 전용 — facilities 라우터와 동일 관례)
unit_type별 도면 1건(scope=unit_type 고정, 시드 스크립트와 동일 모델). 업로드는
unit_type_name 기준 get-or-create → 기존 도면 있으면 이미지만 교체(devices 보존,
version+1), 없으면 신규 생성. 이미지 크기(width/height)는 Pillow 등 서버측 이미지 처리
의존성이 없어 **클라이언트가 폼 필드로 제출**한다(계약 확정 — 브리프 조사 결과). devices는
PUT으로 항상 **전체 교체**(delete-then-insert, 시드와 동일 멱등 패턴) — action='base'·
household_id=NULL 고정(세대 오버라이드는 미구현 범위 밖).

업로드·devices PUT 성공 시 도면+마커 스냅샷을 `outbox_events(aggregate_type='floor_plan')`에
도메인 행과 한 트랜잭션으로 기록한다(H13-6, 그래프 반영은 ai-worker가 폴링 — §13.3 관례).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, Storage, get_storage, get_tenant_session, require_roles
from app.outbox import record_outbox
from app.schemas.floor_plans import (
    AdminFloorPlanDetailOut,
    AdminFloorPlanListItemOut,
    AdminFloorPlanListOut,
    AdminPlanDevicesReplaceIn,
    FloorPlanOut,
    MyFloorPlanOut,
    PlanDeviceOut,
)
from liviq_db.models import Facility, FloorPlan, HouseholdGeometry, PlanDevice, UnitType, User

router = APIRouter(tags=["floor-plans"])

_RESIDENT = require_roles("RESIDENT")
_MANAGER = require_roles("MANAGER")

ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB — 도면 이미지 상한


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

    devices = await session.scalars(_base_devices_stmt(ctx.tenant_id, plan.id))

    image_url = await storage.presigned_get_url(plan.image_key)
    return MyFloorPlanOut(
        plan=FloorPlanOut(
            id=plan.id,
            image_url=image_url,
            image_width=plan.image_width,
            image_height=plan.image_height,
            unit_type_name=unit_type.name,
        ),
        devices=[_plan_device_out(d) for d in devices],
    )


def _base_devices_stmt(tenant_id: uuid.UUID, floor_plan_id: uuid.UUID) -> Select[tuple[PlanDevice]]:
    """base·세대 오버라이드 없는 장치 전부(§4.8 오버라이드 미구현 범위) — /me·관리자 공용."""
    return (
        select(PlanDevice)
        .where(
            PlanDevice.tenant_id == tenant_id,
            PlanDevice.floor_plan_id == floor_plan_id,
            PlanDevice.household_id.is_(None),
            PlanDevice.action == "base",
        )
        .order_by(PlanDevice.created_at)
    )


def _floor_plan_snapshot(
    unit_type_name: str, plan: FloorPlan, devices: Sequence[PlanDevice]
) -> dict[str, Any]:
    """graph-sync 워커가 payload만으로 Neo4j MERGE하도록 도면+마커 스냅샷 전부 담는다(§4.9).

    memo·photo_key는 표시용이라 싣지 않는다(그래프는 위치 렌즈 목적, 규칙 7).
    """
    return {
        "unit_type_name": unit_type_name,
        "image_width": plan.image_width,
        "image_height": plan.image_height,
        "devices": [
            {
                "pg_id": d.id,
                "device_type": d.device_type,
                "x": d.x,
                "y": d.y,
                "room": d.room,
                "dir": d.dir,
                "label": d.label,
                "facility_id": d.facility_id,
            }
            for d in devices
        ],
    }


def _plan_device_out(d: PlanDevice) -> PlanDeviceOut:
    return PlanDeviceOut(
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


# ── 관리자 평면도 편집 (MANAGER 전용, H13-4) ─────────────────────────────────


async def _get_admin_plan(
    session: AsyncSession, tenant_id: uuid.UUID, floor_plan_id: uuid.UUID
) -> FloorPlan:
    """tenant 소유의 unit_type 스코프 도면 조회 — 없으면 404(격리 유지, 존재 비노출)."""
    plan = await session.scalar(
        select(FloorPlan).where(
            FloorPlan.id == floor_plan_id,
            FloorPlan.tenant_id == tenant_id,
            FloorPlan.scope == "unit_type",
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="평면도를 찾을 수 없음")
    return plan


async def _get_or_create_unit_type(
    session: AsyncSession, tenant_id: uuid.UUID, name: str
) -> UnitType:
    unit_type = await session.scalar(
        select(UnitType).where(UnitType.tenant_id == tenant_id, UnitType.name == name)
    )
    if unit_type is None:
        unit_type = UnitType(tenant_id=tenant_id, name=name)
        session.add(unit_type)
        await session.flush()
    return unit_type


async def _read_validated_image(file: UploadFile) -> tuple[bytes, str]:
    """확장자 화이트리스트·크기·빈 파일 검증 후 (bytes, suffix) 반환(documents 관례 재사용)."""
    filename = file.filename or ""
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        detail = f"허용되지 않는 이미지 형식: {suffix or '없음'}"
        raise HTTPException(status_code=422, detail=detail)
    data = await file.read()
    if len(data) > MAX_IMAGE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="이미지가 10MB를 초과")
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일")
    return data, suffix


@router.get("/admin/floor-plans", response_model=AdminFloorPlanListOut)
async def list_admin_floor_plans(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> AdminFloorPlanListOut:
    rows = await session.execute(
        select(FloorPlan, UnitType.name, func.count(PlanDevice.id))
        .join(UnitType, UnitType.id == FloorPlan.unit_type_id)
        .outerjoin(
            PlanDevice,
            (PlanDevice.floor_plan_id == FloorPlan.id)
            & (PlanDevice.tenant_id == FloorPlan.tenant_id),
        )
        .where(FloorPlan.tenant_id == ctx.tenant_id, FloorPlan.scope == "unit_type")
        .group_by(FloorPlan.id, UnitType.name)
        .order_by(UnitType.name)
    )
    items = [
        AdminFloorPlanListItemOut(
            id=plan.id,
            unit_type_name=unit_type_name,
            image_url=await storage.presigned_get_url(plan.image_key),
            image_width=plan.image_width,
            image_height=plan.image_height,
            device_count=device_count,
            updated_at=plan.updated_at,
        )
        for plan, unit_type_name, device_count in rows.all()
    ]
    return AdminFloorPlanListOut(items=items)


@router.get("/admin/floor-plans/{floor_plan_id}", response_model=AdminFloorPlanDetailOut)
async def get_admin_floor_plan(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    floor_plan_id: uuid.UUID,
) -> AdminFloorPlanDetailOut:
    plan = await _get_admin_plan(session, ctx.tenant_id, floor_plan_id)
    unit_type_name = await session.scalar(
        select(UnitType.name).where(
            UnitType.tenant_id == ctx.tenant_id, UnitType.id == plan.unit_type_id
        )
    )
    devices = await session.scalars(_base_devices_stmt(ctx.tenant_id, plan.id))
    return AdminFloorPlanDetailOut(
        plan=FloorPlanOut(
            id=plan.id,
            image_url=await storage.presigned_get_url(plan.image_key),
            image_width=plan.image_width,
            image_height=plan.image_height,
            unit_type_name=unit_type_name or "",
        ),
        devices=[_plan_device_out(d) for d in devices],
    )


@router.post("/admin/floor-plans", response_model=AdminFloorPlanListItemOut)
async def upsert_admin_floor_plan(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    unit_type_name: Annotated[str, Form(min_length=1, max_length=100)],
    image: Annotated[UploadFile, File()],
    image_width: Annotated[int, Form(gt=0)],
    image_height: Annotated[int, Form(gt=0)],
) -> AdminFloorPlanListItemOut:
    """unit_type_name get-or-create 후 도면 업서트 — 기존 타입이면 이미지만 교체(devices 보존,
    version+1), 신규 타입이면 새 도면 생성(devices 0건)."""
    data, suffix = await _read_validated_image(image)
    unit_type = await _get_or_create_unit_type(session, ctx.tenant_id, unit_type_name)

    plan = await session.scalar(
        select(FloorPlan).where(
            FloorPlan.tenant_id == ctx.tenant_id,
            FloorPlan.scope == "unit_type",
            FloorPlan.unit_type_id == unit_type.id,
        )
    )
    is_new = plan is None
    version = (plan.version + 1) if plan is not None else 1
    image_key = f"{ctx.tenant_id}/floor-plans/{unit_type.name}/v{version}{suffix}"
    await storage.put(image_key, data)

    if plan is None:
        plan = FloorPlan(
            tenant_id=ctx.tenant_id,
            scope="unit_type",
            unit_type_id=unit_type.id,
            image_key=image_key,
            image_width=image_width,
            image_height=image_height,
            version=version,
        )
        session.add(plan)
    else:
        plan.image_key = image_key
        plan.image_width = image_width
        plan.image_height = image_height
        plan.version = version
    await session.flush()
    await session.refresh(plan)

    devices = list(await session.scalars(_base_devices_stmt(ctx.tenant_id, plan.id)))
    await record_outbox(
        session,
        tenant_id=ctx.tenant_id,
        aggregate_type="floor_plan",
        aggregate_id=plan.id,
        event_type="created" if is_new else "updated",
        payload=_floor_plan_snapshot(unit_type.name, plan, devices),
    )

    device_count = len(devices)
    return AdminFloorPlanListItemOut(
        id=plan.id,
        unit_type_name=unit_type.name,
        image_url=await storage.presigned_get_url(plan.image_key),
        image_width=plan.image_width,
        image_height=plan.image_height,
        device_count=device_count or 0,
        updated_at=plan.updated_at,
    )


async def _validate_facility_ids(
    session: AsyncSession, tenant_id: uuid.UUID, facility_ids: set[uuid.UUID]
) -> None:
    if not facility_ids:
        return
    found = set(
        await session.scalars(
            select(Facility.id).where(
                Facility.tenant_id == tenant_id,
                Facility.id.in_(facility_ids),
                Facility.deleted_at.is_(None),
            )
        )
    )
    missing = facility_ids - found
    if missing:
        raise HTTPException(status_code=422, detail="존재하지 않는 facility_id")


@router.put("/admin/floor-plans/{floor_plan_id}/devices", response_model=AdminFloorPlanDetailOut)
async def replace_admin_plan_devices(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    floor_plan_id: uuid.UUID,
    body: AdminPlanDevicesReplaceIn,
) -> AdminFloorPlanDetailOut:
    plan = await _get_admin_plan(session, ctx.tenant_id, floor_plan_id)

    if plan.image_width is not None and plan.image_height is not None:
        for i, d in enumerate(body.devices):
            if d.x > plan.image_width or d.y > plan.image_height:
                raise HTTPException(
                    status_code=422, detail=f"장치 좌표가 이미지 범위를 벗어남(index={i})"
                )
    facility_ids = {d.facility_id for d in body.devices if d.facility_id is not None}
    await _validate_facility_ids(session, ctx.tenant_id, facility_ids)

    # 전체 교체(delete-then-insert) — 시드 스크립트와 동일 멱등 패턴(오버라이드 미구현이라
    # 이 floor_plan의 plan_devices는 현재 전부 base 행뿐).
    await session.execute(
        delete(PlanDevice).where(
            PlanDevice.tenant_id == ctx.tenant_id, PlanDevice.floor_plan_id == plan.id
        )
    )
    session.add_all(
        [
            PlanDevice(
                tenant_id=ctx.tenant_id,
                floor_plan_id=plan.id,
                action="base",
                device_type=d.device_type,
                x=d.x,
                y=d.y,
                room=d.room,
                dir=d.dir,
                label=d.label,
                memo=d.memo,
                facility_id=d.facility_id,
            )
            for d in body.devices
        ]
    )
    await session.flush()

    unit_type_name = await session.scalar(
        select(UnitType.name).where(
            UnitType.tenant_id == ctx.tenant_id, UnitType.id == plan.unit_type_id
        )
    )
    devices = list(await session.scalars(_base_devices_stmt(ctx.tenant_id, plan.id)))
    await record_outbox(
        session,
        tenant_id=ctx.tenant_id,
        aggregate_type="floor_plan",
        aggregate_id=plan.id,
        event_type="updated",
        payload=_floor_plan_snapshot(unit_type_name or "", plan, devices),
    )
    return AdminFloorPlanDetailOut(
        plan=FloorPlanOut(
            id=plan.id,
            image_url=await storage.presigned_get_url(plan.image_key),
            image_width=plan.image_width,
            image_height=plan.image_height,
            unit_type_name=unit_type_name or "",
        ),
        devices=[_plan_device_out(d) for d in devices],
    )
