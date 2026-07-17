"""facilities 라우터 통합 — 실 PG. CRUD·이력·outbox 원자성·역할·tenant 격리 (docs/01 §13).

원자성 불변식(docs/03 §4.9): 도메인 쓰기 트랜잭션마다 outbox_events가 함께 기록된다.
sequence는 aggregate_id별 단조 증가(첫 이벤트=1), payload는 그래프 반영용 행 스냅샷 전부.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_tenant_session
from app.main import create_app
from conftest import TENANT_ID
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import OutboxEvent, Tenant

OTHER_TENANT_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")
MANAGER_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
FACILITY_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000002")
RESIDENT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()


def _make_client(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID = TENANT_ID,
    user_id: uuid.UUID = MANAGER_ID,
    roles: tuple[str, ...] = ("MANAGER",),
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(tenant_id, user_id, roles=roles)
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await _seed(db_session)
    yield db_session


async def _create_facility(
    client: httpx.AsyncClient, *, name: str = "1203동 승강기", status: str = "fault"
) -> dict[str, object]:
    response = await client.post(
        "/admin/facilities",
        json={"name": name, "location": "1203동", "type": "elevator", "status": status},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _outbox_rows(session: AsyncSession, aggregate_id: uuid.UUID) -> list[OutboxEvent]:
    rows = await session.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.aggregate_id == aggregate_id)
        .order_by(OutboxEvent.sequence)
    )
    return list(rows)


# ── CRUD 흐름 ────────────────────────────────────────────────────────────────


async def test_create_list_detail_patch_and_history_flow(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as c:
        created = await _create_facility(c)
        fid = created["id"]
        assert created["status"] == "fault"

        listed = (await c.get("/admin/facilities")).json()
        assert listed["total"] == 1
        assert [f["id"] for f in listed["items"]] == [fid]

        patched = await c.patch(f"/admin/facilities/{fid}", json={"status": "check"})
        assert patched.status_code == 200
        assert patched.json()["status"] == "check"

        inc = await c.post(
            f"/admin/facilities/{fid}/incidents",
            json={"symptom": "덜컹 소음", "resolution": "롤러 교체"},
        )
        assert inc.status_code == 201
        assert inc.json()["occurred_at"] is not None  # 기본 now

        maint = await c.post(
            f"/admin/facilities/{fid}/maintenance",
            json={"work": "정기 점검", "performer": "김기사", "parts": {"roller": 2}},
        )
        assert maint.status_code == 201

        detail = (await c.get(f"/admin/facilities/{fid}")).json()
        assert detail["status"] == "check"
        assert [i["symptom"] for i in detail["incidents"]] == ["덜컹 소음"]
        assert [m["work"] for m in detail["maintenance_logs"]] == ["정기 점검"]
        assert detail["maintenance_logs"][0]["parts"] == {"roller": 2}


async def test_list_filters_by_status_and_type(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as c:
        fault = await _create_facility(c, name="승강기", status="fault")
        await _create_facility(c, name="펌프", status="normal")

        by_status = (await c.get("/admin/facilities", params={"status": "fault"})).json()
        assert [f["id"] for f in by_status["items"]] == [fault["id"]]
        assert by_status["total"] == 1

        by_type = (await c.get("/admin/facilities", params={"type": "elevator"})).json()
        assert by_type["total"] == 2  # 둘 다 type=elevator


# ── 원자성 (outbox) ──────────────────────────────────────────────────────────


async def test_create_records_outbox_snapshot(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as c:
        created = await _create_facility(c)

    events = await _outbox_rows(seeded, uuid.UUID(str(created["id"])))
    assert len(events) == 1
    ev = events[0]
    assert ev.aggregate_type == "facility"
    assert ev.event_type == "created"
    assert ev.sequence == 1
    assert ev.status == "pending"
    assert ev.dedupe_key == f"facility:{created['id']}:1"
    assert ev.payload == {
        "name": "1203동 승강기",
        "location": "1203동",
        "type": "elevator",
        "status": "fault",
    }


async def test_facility_patch_increments_sequence(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as c:
        created = await _create_facility(c)
        fid = created["id"]
        await c.patch(f"/admin/facilities/{fid}", json={"status": "check"})
        await c.patch(f"/admin/facilities/{fid}", json={"status": "normal"})

    events = await _outbox_rows(seeded, uuid.UUID(str(fid)))
    assert [(e.event_type, e.sequence) for e in events] == [
        ("created", 1),
        ("updated", 2),
        ("updated", 3),
    ]


async def test_each_incident_is_own_aggregate_sequence_one(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as c:
        created = await _create_facility(c)
        fid = created["id"]
        first = (
            await c.post(f"/admin/facilities/{fid}/incidents", json={"symptom": "소음"})
        ).json()
        second = (
            await c.post(f"/admin/facilities/{fid}/incidents", json={"symptom": "정지"})
        ).json()

    for inc in (first, second):
        events = await _outbox_rows(seeded, uuid.UUID(str(inc["id"])))
        assert len(events) == 1
        assert events[0].aggregate_type == "incident"
        assert events[0].sequence == 1
    # incident payload 스냅샷 필드 확인
    ev = (await _outbox_rows(seeded, uuid.UUID(str(first["id"]))))[0]
    assert ev.payload is not None
    assert ev.payload["symptom"] == "소음"
    assert ev.payload["facility_id"] == str(fid)


async def test_maintenance_records_outbox(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as c:
        created = await _create_facility(c)
        fid = created["id"]
        log = (
            await c.post(
                f"/admin/facilities/{fid}/maintenance",
                json={"work": "점검", "parts": {"belt": 1, "seals": ["a", "b"]}},
            )
        ).json()

    events = await _outbox_rows(seeded, uuid.UUID(str(log["id"])))
    assert len(events) == 1
    assert events[0].aggregate_type == "maintenance_log"
    assert events[0].event_type == "created"
    assert events[0].payload is not None
    assert events[0].payload["parts"] == {"belt": 1, "seals": ["a", "b"]}


# ── 역할 (CRITICAL) ──────────────────────────────────────────────────────────


async def test_resident_forbidden_on_writes(seeded: AsyncSession) -> None:
    fake = uuid.uuid4()
    async with _make_client(seeded, user_id=RESIDENT_ID, roles=("RESIDENT",)) as c:
        assert (
            await c.post("/admin/facilities", json={"name": "x", "status": "normal"})
        ).status_code == 403
        assert (
            await c.patch(f"/admin/facilities/{fake}", json={"status": "check"})
        ).status_code == 403
        assert (
            await c.post(f"/admin/facilities/{fake}/incidents", json={"symptom": "s"})
        ).status_code == 403
        assert (
            await c.post(f"/admin/facilities/{fake}/maintenance", json={"work": "w"})
        ).status_code == 403
        assert (await c.get("/admin/facilities")).status_code == 403  # 읽기도 RESIDENT 제외


async def test_staff_can_read_but_not_write(seeded: AsyncSession) -> None:
    async with _make_client(seeded, roles=("MANAGER",)) as mgr:
        created = await _create_facility(mgr)
    async with _make_client(seeded, roles=("STAFF",)) as staff:
        assert (await staff.get("/admin/facilities")).status_code == 200
        assert (await staff.get(f"/admin/facilities/{created['id']}")).status_code == 200
        assert (
            await staff.patch(f"/admin/facilities/{created['id']}", json={"status": "check"})
        ).status_code == 403


async def test_facility_role_can_write(seeded: AsyncSession) -> None:
    async with _make_client(seeded, user_id=FACILITY_ID, roles=("FACILITY",)) as c:
        response = await c.post("/admin/facilities", json={"name": "보안등", "status": "normal"})
    assert response.status_code == 201


# ── tenant 격리 ──────────────────────────────────────────────────────────────


async def test_other_tenant_cannot_read_facility(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as owner:
        created = await _create_facility(owner)
    async with _make_client(seeded, tenant_id=OTHER_TENANT_ID) as other:
        assert (await other.get(f"/admin/facilities/{created['id']}")).status_code == 404
        assert (
            await other.patch(f"/admin/facilities/{created['id']}", json={"status": "check"})
        ).status_code == 404
