"""facilities — 시설 CRUD·장애·정비 이력 + outbox 원자 기록 (docs/01 §13).

쓰기 트랜잭션마다 도메인 행과 outbox_events를 원자적으로 기록한다(이중 쓰기 금지,
docs/03 §4.9·docs/11 §3.5). Neo4j 반영은 ai-worker(H3-2)가 outbox를 폴링해 단독 수행 —
이 라우터는 그래프에 직접 쓰지 않는다(§13.3). AI 제안·자동 상태 변경 없음(규칙 8).

역할: 시설은 전부 소장(MANAGER) 전용(H7-2에서 FACILITY·STAFF 제거, docs/04 §4).
모든 조회·수정은 tenant 스코프 — 없는 tenant면 404(격리 위해 존재 여부 노출 안 함).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_tenant_session, require_roles
from app.outbox import record_outbox
from app.schemas.facilities import (
    FacilityCreateIn,
    FacilityDetailOut,
    FacilityListOut,
    FacilityOut,
    FacilityPatchIn,
    FacilityStatus,
    IncidentCreateIn,
    IncidentOut,
    MaintenanceCreateIn,
    MaintenanceOut,
)
from liviq_db.models import Facility, Incident, MaintenanceLog

router = APIRouter(prefix="/admin/facilities", tags=["facilities"])

_READ_ROLES = ("MANAGER",)
_WRITE_ROLES = ("MANAGER",)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def _get_facility(
    session: AsyncSession, tenant_id: uuid.UUID, facility_id: uuid.UUID
) -> Facility:
    facility = await session.scalar(
        select(Facility).where(
            Facility.id == facility_id,
            Facility.tenant_id == tenant_id,
            Facility.deleted_at.is_(None),
        )
    )
    if facility is None:
        raise HTTPException(status_code=404, detail="시설을 찾을 수 없음")
    return facility


def _facility_out(facility: Facility) -> FacilityOut:
    return FacilityOut.model_validate(facility, from_attributes=True)


def _facility_snapshot(facility: Facility) -> dict[str, object | None]:
    """graph-sync 워커가 payload만으로 Neo4j MERGE하도록 행 스냅샷 전부 담는다(docs/03 §5)."""
    return {
        "name": facility.name,
        "location": facility.location,
        "type": facility.type,
        "status": facility.status,
    }


@router.get("", response_model=FacilityListOut)
async def list_facilities(
    ctx: Annotated[RequestContext, Depends(require_roles(*_READ_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    status: Annotated[FacilityStatus | None, Query()] = None,
    type: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> FacilityListOut:
    base = select(Facility).where(
        Facility.tenant_id == ctx.tenant_id, Facility.deleted_at.is_(None)
    )
    if status is not None:
        base = base.where(Facility.status == status)
    if type is not None:
        base = base.where(Facility.type == type)
    total = await session.scalar(select(func.count()).select_from(base.order_by(None).subquery()))
    rows = await session.scalars(
        base.order_by(Facility.name).offset((page - 1) * limit).limit(limit)
    )
    return FacilityListOut(items=[_facility_out(row) for row in rows], total=total or 0)


@router.post("", response_model=FacilityOut, status_code=201)
async def create_facility(
    ctx: Annotated[RequestContext, Depends(require_roles(*_WRITE_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    body: FacilityCreateIn,
) -> FacilityOut:
    facility = Facility(
        tenant_id=ctx.tenant_id,
        name=body.name,
        location=body.location,
        type=body.type,
        status=body.status,
        next_check_at=body.next_check_at,
    )
    session.add(facility)
    await session.flush()
    await record_outbox(
        session,
        tenant_id=ctx.tenant_id,
        aggregate_type="facility",
        aggregate_id=facility.id,
        event_type="created",
        payload=_facility_snapshot(facility),
    )
    return _facility_out(facility)


@router.get("/{facility_id}", response_model=FacilityDetailOut)
async def get_facility(
    ctx: Annotated[RequestContext, Depends(require_roles(*_READ_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    facility_id: uuid.UUID,
) -> FacilityDetailOut:
    facility = await _get_facility(session, ctx.tenant_id, facility_id)
    incidents = await session.scalars(
        select(Incident)
        .where(Incident.tenant_id == ctx.tenant_id, Incident.facility_id == facility_id)
        .order_by(Incident.created_at.desc())
    )
    logs = await session.scalars(
        select(MaintenanceLog)
        .where(
            MaintenanceLog.tenant_id == ctx.tenant_id,
            MaintenanceLog.facility_id == facility_id,
        )
        .order_by(MaintenanceLog.created_at.desc())
    )
    return FacilityDetailOut(
        **_facility_out(facility).model_dump(),
        incidents=[IncidentOut.model_validate(i, from_attributes=True) for i in incidents],
        maintenance_logs=[MaintenanceOut.model_validate(m, from_attributes=True) for m in logs],
    )


@router.patch("/{facility_id}", response_model=FacilityOut)
async def patch_facility(
    ctx: Annotated[RequestContext, Depends(require_roles(*_WRITE_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    facility_id: uuid.UUID,
    body: FacilityPatchIn,
) -> FacilityOut:
    facility = await _get_facility(session, ctx.tenant_id, facility_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(facility, field, value)
    await session.flush()
    await record_outbox(
        session,
        tenant_id=ctx.tenant_id,
        aggregate_type="facility",
        aggregate_id=facility.id,
        event_type="updated",
        payload=_facility_snapshot(facility),
    )
    return _facility_out(facility)


@router.post("/{facility_id}/incidents", response_model=IncidentOut, status_code=201)
async def create_incident(
    ctx: Annotated[RequestContext, Depends(require_roles(*_WRITE_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    facility_id: uuid.UUID,
    body: IncidentCreateIn,
) -> IncidentOut:
    await _get_facility(session, ctx.tenant_id, facility_id)
    incident = Incident(
        tenant_id=ctx.tenant_id,
        facility_id=facility_id,
        occurred_at=body.occurred_at or _now(),
        symptom=body.symptom,
        resolution=body.resolution,
        root_cause=body.root_cause,
    )
    session.add(incident)
    await session.flush()
    await record_outbox(
        session,
        tenant_id=ctx.tenant_id,
        aggregate_type="incident",
        aggregate_id=incident.id,
        event_type="created",
        payload={
            "facility_id": incident.facility_id,
            "occurred_at": incident.occurred_at,
            "symptom": incident.symptom,
            "resolution": incident.resolution,
            "root_cause": incident.root_cause,
        },
    )
    return IncidentOut.model_validate(incident, from_attributes=True)


@router.post("/{facility_id}/maintenance", response_model=MaintenanceOut, status_code=201)
async def create_maintenance(
    ctx: Annotated[RequestContext, Depends(require_roles(*_WRITE_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    facility_id: uuid.UUID,
    body: MaintenanceCreateIn,
) -> MaintenanceOut:
    await _get_facility(session, ctx.tenant_id, facility_id)
    log = MaintenanceLog(
        tenant_id=ctx.tenant_id,
        facility_id=facility_id,
        performed_at=body.performed_at or _now(),
        work=body.work,
        performer=body.performer,
        parts=body.parts,
    )
    session.add(log)
    await session.flush()
    await record_outbox(
        session,
        tenant_id=ctx.tenant_id,
        aggregate_type="maintenance_log",
        aggregate_id=log.id,
        event_type="created",
        payload={
            "facility_id": log.facility_id,
            "performed_at": log.performed_at,
            "work": log.work,
            "performer": log.performer,
            "parts": log.parts,
        },
    )
    return MaintenanceOut.model_validate(log, from_attributes=True)
