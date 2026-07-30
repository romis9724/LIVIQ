"""seed_graph.py — 첫마을 4단지 그래프 시드 (G1b, GraphRAG 비교용).

회의록 정합 장애(incidents 16) · 정비 이력(maintenance_logs 22) · 세대기기→설비
LINKED_TO 배선(plan_devices.facility_id)을 적재한다. 상수는 scripts/data/graph_seed.py,
설계 단일 출처는 evals/fixtures/chetmaeul-v2/SEED-PLAN.md §1·§2·§4·§5.

멱등: incident 자연키 (tenant_id, facility_id, symptom) · maintenance 자연키
(tenant_id, facility_id, work) upsert. 재실행해도 개수가 늘지 않는다.

인과 연쇄(CAUSED_BY)는 2패스로 배선한다 — 1패스에서 전건 upsert 후 key→id 맵을 만들고,
2패스에서 caused_by_incident_id를 채운다(원인이 뒤에 정의돼도 안전). 그래프 워커는
outbox payload의 caused_by_incident_id를 읽어 CAUSED_BY 엣지를 만들므로(graph_sync.py)
payload에 반드시 포함한다.

배선된 plan_device가 속한 floor_plan을 재-emit해야 LINKED_TO가 Neo4j에 재색인된다
(client.py가 device.facility_id로 PlanDevice-[:LINKED_TO]->Facility를 만든다).

불변(SEED-PLAN §5): facilities.status(전부 normal)·next_check_at(전부 NULL)은
건드리지 않는다 — 시드 후 같은 트랜잭션에서 assert로 확인한다.

도메인 행 변경과 outbox_events 기록은 한 트랜잭션(이중 쓰기 금지, docs/03 §4.9).

실행(DATABASE_URL은 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync python scripts/seed_graph.py [--tenant-id <uuid>]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import sys
import uuid
from pathlib import Path

from app.outbox import record_outbox
from app.routers.floor_plans import _floor_plan_snapshot
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import (
    Facility,
    FloorPlan,
    Incident,
    MaintenanceLog,
    PlanDevice,
    Tenant,
    UnitType,
)

# scripts/data는 namespace 폴더 — 이 파일 디렉터리를 sys.path에 넣어 임포트한다
# (seed_facilities_kapt.py와 동일 관례).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.graph_seed import (  # noqa: E402
    INCIDENTS,
    LINKED_TO_MAP,
    MAINTENANCE,
    IncidentSeed,
    MaintenanceSeed,
)

# 파일럿 단지(첫마을 4단지 푸르지오) — 다른 시드 스크립트와 동일 tenant.
DEFAULT_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# 인과 연쇄 수(SEED-PLAN §1 — #4→#4b·#14→#4·#11→#10·#6→#6b).
EXPECTED_CHAIN_COUNT = 4


def _to_datetime(day: datetime.date) -> datetime.datetime:
    """date를 UTC 자정 datetime으로 — 컬럼이 timezone-aware라 tz를 붙인다(결정론)."""
    return datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.UTC)


async def _facility_ids(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """이름→id 맵. 시드가 참조하는 모든 이름이 있는지 검증 후 없으면 fail-fast."""
    rows = await session.execute(
        select(Facility.name, Facility.id).where(
            Facility.tenant_id == tenant_id,
            Facility.deleted_at.is_(None),
        )
    )
    name_to_id = {name: fid for name, fid in rows.all()}
    referenced = (
        {inc.facility_name for inc in INCIDENTS}
        | {mnt.facility_name for mnt in MAINTENANCE}
        | set(LINKED_TO_MAP.values())
    )
    missing = sorted(referenced - name_to_id.keys())
    if missing:
        raise SystemExit(
            "facilities에 없는 설비 이름(먼저 seed_facilities_kapt.py 실행 필요): "
            + ", ".join(missing)
        )
    return name_to_id


async def _upsert_incident(
    session: AsyncSession, tenant_id: uuid.UUID, facility_id: uuid.UUID, inc: IncidentSeed
) -> tuple[Incident, bool]:
    """자연키 (tenant_id, facility_id, symptom) upsert — (incident, is_new)."""
    existing = await session.scalar(
        select(Incident).where(
            Incident.tenant_id == tenant_id,
            Incident.facility_id == facility_id,
            Incident.symptom == inc.symptom,
        )
    )
    occurred_at = _to_datetime(inc.occurred_at)
    if existing is not None:
        existing.occurred_at = occurred_at
        existing.resolution = inc.resolution
        existing.root_cause = inc.root_cause
        return existing, False
    incident = Incident(
        tenant_id=tenant_id,
        facility_id=facility_id,
        occurred_at=occurred_at,
        symptom=inc.symptom,
        resolution=inc.resolution,
        root_cause=inc.root_cause,
    )
    session.add(incident)
    await session.flush()
    return incident, True


async def _seed_incidents(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    facility_ids: dict[str, uuid.UUID],
) -> tuple[int, int]:
    """incidents 2패스 upsert + CAUSED_BY 배선 + outbox. (신규, 갱신) 반환."""
    id_map: dict[str, Incident] = {}
    new_keys: set[str] = set()
    # 1패스: 전건 upsert(caused_by 미해결) 후 key→incident 맵 축적.
    for inc in INCIDENTS:
        incident, is_new = await _upsert_incident(
            session, tenant_id, facility_ids[inc.facility_name], inc
        )
        id_map[inc.key] = incident
        if is_new:
            new_keys.add(inc.key)
    # 2패스: caused_by가 있는 건의 caused_by_incident_id를 1패스 id로 SET.
    for inc in INCIDENTS:
        cause = id_map[inc.caused_by].id if inc.caused_by else None
        id_map[inc.key].caused_by_incident_id = cause
    await session.flush()
    # outbox: caused_by_incident_id를 payload에 포함(그래프 워커가 CAUSED_BY 엣지에 사용).
    for inc in INCIDENTS:
        incident = id_map[inc.key]
        await record_outbox(
            session,
            tenant_id=tenant_id,
            aggregate_type="incident",
            aggregate_id=incident.id,
            event_type="created" if inc.key in new_keys else "updated",
            payload={
                "facility_id": incident.facility_id,
                "occurred_at": incident.occurred_at,
                "symptom": incident.symptom,
                "resolution": incident.resolution,
                "root_cause": incident.root_cause,
                "caused_by_incident_id": incident.caused_by_incident_id,
            },
        )
    return len(new_keys), len(INCIDENTS) - len(new_keys)


async def _upsert_maintenance(
    session: AsyncSession, tenant_id: uuid.UUID, facility_id: uuid.UUID, mnt: MaintenanceSeed
) -> uuid.UUID:
    """자연키 (tenant_id, facility_id, work) upsert — outbox용 id 반환."""
    performed_at = _to_datetime(mnt.performed_at)
    existing = await session.scalar(
        select(MaintenanceLog).where(
            MaintenanceLog.tenant_id == tenant_id,
            MaintenanceLog.facility_id == facility_id,
            MaintenanceLog.work == mnt.work,
        )
    )
    if existing is not None:
        existing.performed_at = performed_at
        existing.performer = mnt.performer
        existing.parts = mnt.parts
        log = existing
    else:
        log = MaintenanceLog(
            tenant_id=tenant_id,
            facility_id=facility_id,
            performed_at=performed_at,
            work=mnt.work,
            performer=mnt.performer,
            parts=mnt.parts,
        )
        session.add(log)
        await session.flush()
    await record_outbox(
        session,
        tenant_id=tenant_id,
        aggregate_type="maintenance_log",
        aggregate_id=log.id,
        event_type="created" if existing is None else "updated",
        payload={
            "facility_id": log.facility_id,
            "performed_at": log.performed_at,
            "work": log.work,
            "performer": log.performer,
            "parts": log.parts,
        },
    )
    return log.id


async def _wire_linked_to(
    session: AsyncSession, tenant_id: uuid.UUID, facility_ids: dict[str, uuid.UUID]
) -> tuple[int, set[uuid.UUID]]:
    """세대기기 base plan_device의 facility_id 배선. (배선 수, 영향 floor_plan_id) 반환."""
    wired = 0
    affected: set[uuid.UUID] = set()
    for device_type, facility_name in LINKED_TO_MAP.items():
        result = await session.execute(
            update(PlanDevice)
            .where(
                PlanDevice.tenant_id == tenant_id,
                PlanDevice.device_type == device_type,
                PlanDevice.action == "base",
            )
            .values(facility_id=facility_ids[facility_name])
            .returning(PlanDevice.floor_plan_id)
        )
        plan_ids = [row[0] for row in result.all()]
        wired += len(plan_ids)
        affected.update(plan_ids)
    return wired, affected


async def _reemit_floor_plan(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    floor_plan_id: uuid.UUID,
    complex_name: str | None,
) -> None:
    """배선 후 floor_plan을 재-emit — 그래프가 LINKED_TO를 재색인하게 한다."""
    plan = await session.scalar(
        select(FloorPlan).where(FloorPlan.id == floor_plan_id, FloorPlan.tenant_id == tenant_id)
    )
    if plan is None:  # 방금 배선된 device의 부모라 정상 경로에선 발생하지 않는다.
        return
    unit_type_name = await session.scalar(
        select(UnitType.name).where(
            UnitType.id == plan.unit_type_id, UnitType.tenant_id == tenant_id
        )
    )
    devices = (
        await session.scalars(
            select(PlanDevice).where(
                PlanDevice.tenant_id == tenant_id,
                PlanDevice.floor_plan_id == floor_plan_id,
            )
        )
    ).all()
    await record_outbox(
        session,
        tenant_id=tenant_id,
        aggregate_type="floor_plan",
        aggregate_id=floor_plan_id,
        event_type="updated",
        payload=_floor_plan_snapshot(unit_type_name or "", plan, list(devices), complex_name),
    )


async def _assert_facility_invariant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """불변(SEED-PLAN §5): status 전부 normal · next_check_at 전부 NULL(시드가 안 건드림)."""
    bad = await session.scalar(
        select(func.count())
        .select_from(Facility)
        .where(
            Facility.tenant_id == tenant_id,
            Facility.deleted_at.is_(None),
            (Facility.status != "normal") | Facility.next_check_at.isnot(None),
        )
    )
    if bad:
        raise RuntimeError(
            f"불변 위반: status≠normal 또는 next_check_at≠NULL인 시설 {bad}건 — 시드 중단"
        )


def _report(new_inc: int, upd_inc: int, mnt: int, wired: int, plans: int) -> None:
    print(f"incidents: 신규 {new_inc} · 갱신 {upd_inc} (총 {len(INCIDENTS)})")
    print(f"maintenance_logs: {mnt}건 (총 {len(MAINTENANCE)})")
    print(f"plan_devices.facility_id 배선: {wired}건 · 재-emit floor_plan {plans}건")
    print(f"CAUSED_BY 인과 연쇄: {EXPECTED_CHAIN_COUNT}건")


async def _run(tenant_id: uuid.UUID) -> None:
    engine = create_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            complex_name = await session.scalar(select(Tenant.name).where(Tenant.id == tenant_id))
            if complex_name is None:
                raise SystemExit(f"단지를 찾을 수 없습니다: {tenant_id}")
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            facility_ids = await _facility_ids(session, tenant_id)

            new_inc, upd_inc = await _seed_incidents(session, tenant_id, facility_ids)
            for mnt in MAINTENANCE:
                await _upsert_maintenance(session, tenant_id, facility_ids[mnt.facility_name], mnt)
            wired, affected = await _wire_linked_to(session, tenant_id, facility_ids)
            for floor_plan_id in sorted(affected, key=str):
                await _reemit_floor_plan(session, tenant_id, floor_plan_id, complex_name)

            await _assert_facility_invariant(session, tenant_id)
        _report(new_inc, upd_inc, len(MAINTENANCE), wired, len(affected))
        print(f"단지: {tenant_id}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="첫마을 4단지 그래프 시드(G1b, GraphRAG 비교)")
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        default=DEFAULT_TENANT_ID,
        help=f"대상 단지 UUID (기본: 첫마을 4단지 {DEFAULT_TENANT_ID})",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.tenant_id))


if __name__ == "__main__":
    main()
