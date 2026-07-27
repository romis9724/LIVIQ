"""facilities — 시설 CRUD·장애·정비 이력 + outbox 원자 기록 (docs/01 §13).

쓰기 트랜잭션마다 도메인 행과 outbox_events를 원자적으로 기록한다(이중 쓰기 금지,
docs/03 §4.9·docs/11 §3.5). Neo4j 반영은 ai-worker(H3-2)가 outbox를 폴링해 단독 수행 —
이 라우터는 그래프에 직접 쓰지 않는다(§13.3). AI 제안·자동 상태 변경 없음(규칙 8).

역할: 시설은 전부 소장(MANAGER) 전용(H7-2에서 FACILITY·STAFF 제거, docs/04 §4).
모든 조회·수정은 tenant 스코프 — 없는 tenant면 404(격리 위해 존재 여부 노출 안 함).
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.graph import GraphClient
from app.deps import RequestContext, get_graph, get_tenant_session, require_roles
from app.outbox import record_outbox
from app.schemas.facilities import (
    FacilityCreateIn,
    FacilityDetailOut,
    FacilityGraphOut,
    FacilityListOut,
    FacilityOut,
    FacilityPatchIn,
    FacilityStatus,
    GraphLinkOut,
    GraphNodeOut,
    IncidentCreateIn,
    IncidentOut,
    MaintenanceCreateIn,
    MaintenanceOut,
)
from liviq_db.models import Facility, Incident, MaintenanceLog, Tenant

logger = logging.getLogger("app.facilities")

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


async def _tenant_name(session: AsyncSession, tenant_id: uuid.UUID) -> str | None:
    """단지명 — Complex 그래프 노드용(사용자 요청: 그래프 중심에 단지 노드, H13-7)."""
    return await session.scalar(select(Tenant.name).where(Tenant.id == tenant_id))


def _facility_snapshot(facility: Facility, complex_name: str | None) -> dict[str, object | None]:
    """graph-sync 워커가 payload만으로 Neo4j MERGE하도록 행 스냅샷 전부 담는다(docs/03 §5).

    `deleted_at`은 소프트 삭제 시 tombstone 신호로 쓰인다(H13-6, GraphClient.merge_facility) —
    현재 이 라우터는 소프트 삭제 엔드포인트가 없어 항상 None이지만, 스냅샷 계약에 미리 싣는다.
    `complex_name`은 단지(tenants.name) — 그래프 중심 Complex 노드 실체화용(H13-7).
    """
    return {
        "name": facility.name,
        "location": facility.location,
        "type": facility.type,
        "status": facility.status,
        "deleted_at": facility.deleted_at,
        "complex_name": complex_name,
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
        payload=_facility_snapshot(facility, await _tenant_name(session, ctx.tenant_id)),
    )
    return _facility_out(facility)


@router.get("/graph", response_model=FacilityGraphOut)
async def get_facility_graph(
    ctx: Annotated[RequestContext, Depends(require_roles(*_READ_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    graph: Annotated[GraphClient | None, Depends(get_graph)],
    include_plan: Annotated[bool, Query()] = False,
) -> FacilityGraphOut:
    """시설 그래프(Neo4j 파생) 조회 — 시설관리 메인의 읽기 경로(ADR-0022).

    Neo4j 미가용은 503이 아니다 — PG `facilities`로 노드만 채운 축약 그래프에
    `degraded=True`를 실어 화면이 한계를 표시하게 한다(docs/01 §10 장애 격리).

    `include_plan`은 기본 false — 평면도 마커까지 실으면 도면당 수십개라 과밀(H13-6),
    opt-in 화면에서만 true로 요청한다.
    """
    if graph is not None:
        try:
            result = await graph.fetch_facility_graph(
                tenant_id=str(ctx.tenant_id), include_plan=include_plan
            )
        except Exception:  # noqa: BLE001 — 그래프 미가용이 화면 실패로 번지지 않게(폴백)
            logger.warning("시설 그래프 조회 실패 — PG 축약 폴백", exc_info=True)
        else:
            return FacilityGraphOut(
                nodes=[GraphNodeOut.model_validate(n, from_attributes=True) for n in result.nodes],
                links=[
                    GraphLinkOut.model_validate(link, from_attributes=True) for link in result.links
                ],
                degraded=False,
            )
    return FacilityGraphOut(
        nodes=await _pg_graph_nodes(session, ctx.tenant_id), links=[], degraded=True
    )


async def _pg_graph_nodes(session: AsyncSession, tenant_id: uuid.UUID) -> list[GraphNodeOut]:
    """축약 그래프 노드 — PG 시설 목록(관계 없음). tenant 스코프는 여기서도 강제."""
    rows = await session.scalars(
        select(Facility)
        .where(Facility.tenant_id == tenant_id, Facility.deleted_at.is_(None))
        .order_by(Facility.name)
    )
    return [
        GraphNodeOut(
            pg_id=str(f.id),
            label="facility",
            name=f.name,
            type=f.type,
            location=f.location,
            status=f.status,
        )
        for f in rows
    ]


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
        payload=_facility_snapshot(facility, await _tenant_name(session, ctx.tenant_id)),
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
