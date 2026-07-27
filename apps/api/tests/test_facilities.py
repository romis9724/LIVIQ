"""facilities 라우터 통합 — 실 PG. CRUD·이력·outbox 원자성·역할·tenant 격리 (docs/01 §13).

원자성 불변식(docs/03 §4.9): 도메인 쓰기 트랜잭션마다 outbox_events가 함께 기록된다.
sequence는 aggregate_id별 단조 증가(첫 이벤트=1), payload는 그래프 반영용 행 스냅샷 전부.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_graph, get_tenant_session
from app.main import create_app
from conftest import TENANT_ID
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.graph import FacilityGraph, GraphLink, GraphNode
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


class StubGraph:
    """GraphClient의 그래프 조회만 흉내내는 스텁 — tenant 인자를 기록하고 결과/예외를 낸다."""

    def __init__(self, result: FacilityGraph | None = None, error: Exception | None = None) -> None:
        self.result = result or FacilityGraph(nodes=(), links=())
        self.error = error
        self.calls: list[str] = []

    async def fetch_facility_graph(self, *, tenant_id: str) -> FacilityGraph:
        self.calls.append(tenant_id)
        if self.error is not None:
            raise self.error
        return self.result


def _make_client(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID = TENANT_ID,
    user_id: uuid.UUID = MANAGER_ID,
    roles: tuple[str, ...] = ("MANAGER",),
    graph: StubGraph | None = None,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(tenant_id, user_id, roles=roles)
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_graph] = lambda: graph  # None = Neo4j 미배선
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


# ── 코드번호 (H14-2) ─────────────────────────────────────────────────────────


async def test_create_assigns_code_and_increments_sequence(seeded: AsyncSession) -> None:
    """`{계통약어}-{위치약어}-{연번}` 자동 부여 — 같은 계통·위치면 연번이 올라간다."""
    async with _make_client(seeded) as c:
        first = await _create_facility(c, name="1203동 승강기 1호기")
        second = await _create_facility(c, name="1203동 승강기 2호기")
        other_location = (
            await c.post(
                "/admin/facilities",
                json={"name": "101동 승강기", "location": "101동", "type": "elevator"},
            )
        ).json()
        other_system = (
            await c.post(
                "/admin/facilities",
                json={"name": "1203동 소화전", "location": "1203동", "type": "fire"},
            )
        ).json()

    assert first["code"] == "EL-1203-01"
    assert second["code"] == "EL-1203-02"
    assert other_location["code"] == "EL-101-01"
    assert other_system["code"] == "FR-1203-01"


async def test_create_falls_back_to_general_and_common(seeded: AsyncSession) -> None:
    """type 미지정은 GN, 숫자 없는 위치는 CMN."""
    async with _make_client(seeded) as c:
        anonymous = (await c.post("/admin/facilities", json={"name": "잡설비"})).json()
        office = (
            await c.post(
                "/admin/facilities",
                json={"name": "정문 CCTV", "location": "관리사무소", "type": "security"},
            )
        ).json()

    assert anonymous["code"] == "GN-CMN-01"
    assert office["code"] == "SC-CMN-01"


async def test_code_cannot_be_set_or_changed_by_client(seeded: AsyncSession) -> None:
    """CRITICAL — 코드는 서버 전용. 생성·수정 요청의 code는 스키마에 없어 무시된다."""
    async with _make_client(seeded) as c:
        created = (
            await c.post(
                "/admin/facilities",
                json={
                    "name": "승강기",
                    "location": "1203동",
                    "type": "elevator",
                    "code": "HACK-000-99",
                },
            )
        ).json()
        assert created["code"] == "EL-1203-01"

        patched = await c.patch(
            f"/admin/facilities/{created['id']}", json={"code": "HACK-000-99", "status": "check"}
        )
        assert patched.status_code == 200
        assert patched.json()["code"] == "EL-1203-01"  # 위치·계통이 바뀌어도 코드는 불변
        assert patched.json()["status"] == "check"

        relocated = await c.patch(f"/admin/facilities/{created['id']}", json={"location": "999동"})
        assert relocated.json()["code"] == "EL-1203-01"


async def test_list_filters_by_exact_code(seeded: AsyncSession) -> None:
    """민원 화면이 코드번호로 시설을 찾는 조회 경로."""
    async with _make_client(seeded) as c:
        target = await _create_facility(c, name="1203동 승강기")
        await _create_facility(c, name="1203동 승강기 2호기")

        hit = (await c.get("/admin/facilities", params={"code": target["code"]})).json()
        assert [f["id"] for f in hit["items"]] == [target["id"]]
        assert hit["total"] == 1

        miss = (await c.get("/admin/facilities", params={"code": "EL-1203-99"})).json()
        assert miss["items"] == [] and miss["total"] == 0


async def test_code_is_unique_per_tenant_not_globally(seeded: AsyncSession) -> None:
    """CRITICAL 격리 — 같은 코드가 단지별로 따로 부여되고, 남의 코드는 조회되지 않는다."""
    seeded.add(Tenant(id=OTHER_TENANT_ID, name="단지B", status="active"))
    await seeded.flush()
    async with _make_client(seeded) as owner:
        mine = await _create_facility(owner, name="1203동 승강기")
    async with _make_client(seeded, tenant_id=OTHER_TENANT_ID) as other:
        theirs = await _create_facility(other, name="1203동 승강기")
        found = (await other.get("/admin/facilities", params={"code": mine["code"]})).json()

    assert mine["code"] == theirs["code"] == "EL-1203-01"  # 단지 스코프 연번
    assert mine["id"] != theirs["id"]
    assert [f["id"] for f in found["items"]] == [theirs["id"]]  # 남의 시설이 아니라 자기 시설


async def test_pg_fallback_graph_carries_code(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as c:
        created = await _create_facility(c)
        body = (await c.get("/admin/facilities/graph")).json()  # graph=None → PG 축약

    assert [n["code"] for n in body["nodes"]] == [created["code"]]


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
        "code": "EL-1203-01",  # 그래프 노드 프로퍼티로 흘러간다(H14-2)
        "location": "1203동",
        "type": "elevator",
        "status": "fault",
        "deleted_at": None,
        "complex_name": "단지A",
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


# ── 그래프 조회 (H13-1, ADR-0022) ────────────────────────────────────────────


def _sample_graph(facility_id: str, incident_id: str) -> FacilityGraph:
    return FacilityGraph(
        nodes=(
            GraphNode(
                pg_id=facility_id,
                label="facility",
                name="지하펌프",
                type="급배수",
                location="지하1층",
                status="fault",
            ),
            GraphNode(
                pg_id=incident_id,
                label="incident",
                name="누수",
                at="2026-07-01T00:00:00Z",
                resolved=True,
            ),
        ),
        links=(GraphLink(source=facility_id, target=incident_id, kind="HAS_INCIDENT"),),
    )


async def test_graph_returns_nodes_and_links_without_extra_fields(seeded: AsyncSession) -> None:
    facility_id, incident_id = str(uuid.uuid4()), str(uuid.uuid4())
    stub = StubGraph(_sample_graph(facility_id, incident_id))
    async with _make_client(seeded, graph=stub) as c:
        response = await c.get("/admin/facilities/graph")

    assert response.status_code == 200, response.text
    body = response.json()
    assert stub.calls == [str(TENANT_ID)]  # tenant 인자 강제(격리 CRITICAL)
    assert body["degraded"] is False
    assert [n["pg_id"] for n in body["nodes"]] == [facility_id, incident_id]
    assert body["links"] == [{"source": facility_id, "target": incident_id, "kind": "HAS_INCIDENT"}]
    # 응답 스키마 고정 — embedding 등 여분 필드가 새지 않는다
    assert set(body["nodes"][0]) == {
        "pg_id",
        "label",
        "name",
        "code",
        "type",
        "location",
        "status",
        "at",
        "resolved",
    }
    assert body["nodes"][1]["resolved"] is True


async def test_graph_accepts_location_node_and_link(seeded: AsyncSession) -> None:
    """Location 노드·LOCATED_IN 관계가 응답 스키마를 통과한다(H13-7 회귀)."""
    facility_id, location_id = str(uuid.uuid4()), "지하1층"
    stub = StubGraph(
        FacilityGraph(
            nodes=(
                GraphNode(pg_id=facility_id, label="facility", name="지하펌프", status="fault"),
                GraphNode(pg_id=location_id, label="location", name=location_id),
            ),
            links=(GraphLink(source=facility_id, target=location_id, kind="LOCATED_IN"),),
        )
    )
    async with _make_client(seeded, graph=stub) as c:
        response = await c.get("/admin/facilities/graph")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [n["label"] for n in body["nodes"]] == ["facility", "location"]
    assert body["links"] == [{"source": facility_id, "target": location_id, "kind": "LOCATED_IN"}]


async def test_graph_accepts_complex_node_and_link(seeded: AsyncSession) -> None:
    """Complex(단지 루트) 노드·PART_OF 관계가 응답 스키마를 통과한다(H13-7 회귀)."""
    facility_id, complex_id = str(uuid.uuid4()), "첫마을 4단지 푸르지오"
    stub = StubGraph(
        FacilityGraph(
            nodes=(
                GraphNode(pg_id=facility_id, label="facility", name="지하펌프", status="fault"),
                GraphNode(pg_id=complex_id, label="complex", name=complex_id),
            ),
            links=(GraphLink(source=facility_id, target=complex_id, kind="PART_OF"),),
        )
    )
    async with _make_client(seeded, graph=stub) as c:
        response = await c.get("/admin/facilities/graph")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [n["label"] for n in body["nodes"]] == ["facility", "complex"]
    assert body["links"] == [{"source": facility_id, "target": complex_id, "kind": "PART_OF"}]


async def test_graph_scopes_query_to_caller_tenant(seeded: AsyncSession) -> None:
    """타 tenant 호출은 자기 tenant로만 질의하고, PG 폴백에서도 남의 시설이 새지 않는다."""
    async with _make_client(seeded) as owner:
        await _create_facility(owner)

    stub = StubGraph()
    async with _make_client(seeded, tenant_id=OTHER_TENANT_ID, graph=stub) as other:
        body = (await other.get("/admin/facilities/graph")).json()
    assert stub.calls == [str(OTHER_TENANT_ID)]
    assert body["nodes"] == []

    broken = StubGraph(error=RuntimeError("neo4j down"))
    async with _make_client(seeded, tenant_id=OTHER_TENANT_ID, graph=broken) as other:
        fallback = (await other.get("/admin/facilities/graph")).json()
    assert fallback["degraded"] is True
    assert fallback["nodes"] == []


async def test_graph_falls_back_to_pg_when_neo4j_unavailable(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as owner:
        created = await _create_facility(owner)

    for graph in (StubGraph(error=RuntimeError("neo4j down")), None):  # 예외 · 미배선
        async with _make_client(seeded, graph=graph) as c:
            response = await c.get("/admin/facilities/graph")

        assert response.status_code == 200, response.text  # 503 금지
        body = response.json()
        assert body["degraded"] is True
        assert body["links"] == []
        assert [(n["pg_id"], n["label"], n["status"]) for n in body["nodes"]] == [
            (created["id"], "facility", "fault")
        ]


async def test_graph_is_manager_only(seeded: AsyncSession) -> None:
    async with _make_client(seeded, graph=StubGraph()) as manager:
        assert (await manager.get("/admin/facilities/graph")).status_code == 200
    for user_id, roles in ((FACILITY_ID, ("STAFF",)), (RESIDENT_ID, ("RESIDENT",))):
        async with _make_client(seeded, user_id=user_id, roles=roles, graph=StubGraph()) as c:
            assert (await c.get("/admin/facilities/graph")).status_code == 403


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


async def test_staff_cannot_read_or_write(seeded: AsyncSession) -> None:
    """시설은 소장 전용(H7-2) — STAFF는 조회·수정 모두 403(CRITICAL 역할 축소)."""
    async with _make_client(seeded, roles=("MANAGER",)) as mgr:
        created = await _create_facility(mgr)
    async with _make_client(seeded, user_id=FACILITY_ID, roles=("STAFF",)) as staff:
        assert (await staff.get("/admin/facilities")).status_code == 403
        assert (await staff.get(f"/admin/facilities/{created['id']}")).status_code == 403
        assert (
            await staff.patch(f"/admin/facilities/{created['id']}", json={"status": "check"})
        ).status_code == 403
        assert (
            await staff.post("/admin/facilities", json={"name": "보안등", "status": "normal"})
        ).status_code == 403


# ── tenant 격리 ──────────────────────────────────────────────────────────────


async def test_other_tenant_cannot_read_facility(seeded: AsyncSession) -> None:
    async with _make_client(seeded) as owner:
        created = await _create_facility(owner)
    async with _make_client(seeded, tenant_id=OTHER_TENANT_ID) as other:
        assert (await other.get(f"/admin/facilities/{created['id']}")).status_code == 404
        assert (
            await other.patch(f"/admin/facilities/{created['id']}", json={"status": "check"})
        ).status_code == 404
