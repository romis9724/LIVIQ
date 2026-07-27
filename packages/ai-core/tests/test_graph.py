"""시설 그래프 typed 레이어 — 멱등·역전 방지·tenant 격리(CRITICAL)·parts.

격리는 docs/07 §3 CRITICAL 게이트: cross-tenant 관계 생성·검색 노출이 없어야 한다.
"""

from __future__ import annotations

import uuid
from typing import Any

from ai_core.graph import GraphClient

_DIM = 1024


def _vec(hot: int) -> list[float]:
    v = [0.0] * _DIM
    v[hot] = 1.0
    return v


async def _read(graph: GraphClient, cypher: str, **params: Any) -> list[dict[str, Any]]:
    result = await graph._driver.execute_query(cypher, params, database_="neo4j")
    return [dict(r) for r in result.records]


async def test_merge_facility_idempotent_and_version_reversal(graph: GraphClient) -> None:
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())

    # 최초 + 동일 version 재실행 → 멱등(노드 1개, 값 동일)
    props = {"name": "펌프", "location": "지하", "type": "펌프", "status": "normal"}
    await graph.merge_facility(tenant_id=tenant, pg_id=pg_id, props=props, version=1)
    await graph.merge_facility(tenant_id=tenant, pg_id=pg_id, props=props, version=1)

    rows = await _read(
        graph,
        "MATCH (f:Facility {pg_id:$p, tenant_id:$t}) RETURN f.name AS name, count(*) AS c",
        p=pg_id,
        t=tenant,
    )
    assert rows[0]["c"] == 1
    assert rows[0]["name"] == "펌프"

    # 상위 version 적용 → 갱신
    await graph.merge_facility(
        tenant_id=tenant, pg_id=pg_id, props={**props, "name": "교체된펌프"}, version=2
    )
    # 낮은 version → 역전 방지(no-op)
    await graph.merge_facility(
        tenant_id=tenant, pg_id=pg_id, props={**props, "name": "되돌림"}, version=1
    )
    rows = await _read(graph, "MATCH (f:Facility {pg_id:$p}) RETURN f.name AS name", p=pg_id)
    assert rows[0]["name"] == "교체된펌프"


async def test_cross_tenant_incident_isolation(graph: GraphClient) -> None:
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    facility_b = str(uuid.uuid4())  # tenant B 소유 시설
    incident_a, incident_b = str(uuid.uuid4()), str(uuid.uuid4())

    # tenant B: 시설 + 장애(임베딩)
    await graph.merge_facility(
        tenant_id=tenant_b, pg_id=facility_b, props={"name": "B펌프", "status": "fault"}, version=1
    )
    await graph.merge_incident(
        tenant_id=tenant_b,
        pg_id=incident_b,
        facility_id=facility_b,
        props={"symptom": "누수"},
        version=1,
        embedding=_vec(1),
    )

    # tenant A: B 시설 pg_id를 facility_id로 넘긴 장애 — 교차 관계가 생기면 안 됨
    await graph.merge_incident(
        tenant_id=tenant_a,
        pg_id=incident_a,
        facility_id=facility_b,
        props={"symptom": "소음"},
        version=1,
        embedding=_vec(0),
    )

    # A 장애는 tenant A 시설(stub)에만 연결 — tenant_id가 A뿐
    owners = await _read(
        graph,
        "MATCH (f:Facility)-[:HAS_INCIDENT]->(i:Incident {pg_id:$i}) "
        "RETURN collect(DISTINCT f.tenant_id) AS ts",
        i=incident_a,
    )
    assert owners[0]["ts"] == [tenant_a]

    # tenant B 시설에는 A 장애로의 관계가 없다
    leak = await _read(
        graph,
        "MATCH (f:Facility {pg_id:$fb, tenant_id:$tb})-[:HAS_INCIDENT]->(i:Incident {pg_id:$ia}) "
        "RETURN count(*) AS c",
        fb=facility_b,
        tb=tenant_b,
        ia=incident_a,
    )
    assert leak[0]["c"] == 0

    # 검색: tenant A로 B의 벡터를 질의해도 B 장애는 노출 안 됨
    hits = await graph.search_incidents(tenant_id=tenant_a, query_vector=_vec(1), k=10)
    ids = {h.pg_id for h in hits}
    assert incident_b not in ids
    assert incident_a in ids


async def test_expand_incidents_returns_facility_and_recent_work(graph: GraphClient) -> None:
    tenant, facility = str(uuid.uuid4()), str(uuid.uuid4())
    incident = str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=facility,
        props={"name": "지하펌프", "status": "fault"},
        version=1,
    )
    await graph.merge_incident(
        tenant_id=tenant,
        pg_id=incident,
        facility_id=facility,
        props={"symptom": "누수"},
        version=1,
        embedding=_vec(1),
    )
    await graph.merge_maintenance(
        tenant_id=tenant,
        pg_id=str(uuid.uuid4()),
        facility_id=facility,
        props={"work": "패킹 교체"},
        version=1,
    )

    contexts = await graph.expand_incidents(tenant_id=tenant, pg_ids=[incident])
    assert len(contexts) == 1
    ctx = contexts[0]
    assert ctx.facility_name == "지하펌프"
    assert ctx.facility_status == "fault"
    assert "패킹 교체" in ctx.recent_work


async def test_expand_incidents_empty_ids_returns_empty(graph: GraphClient) -> None:
    assert await graph.expand_incidents(tenant_id=str(uuid.uuid4()), pg_ids=[]) == []


async def test_fetch_facility_graph_shapes_nodes_links_without_embedding(
    graph: GraphClient,
) -> None:
    tenant, facility = str(uuid.uuid4()), str(uuid.uuid4())
    orphan = str(uuid.uuid4())
    incident, log_id = str(uuid.uuid4()), str(uuid.uuid4())

    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=facility,
        props={"name": "지하펌프", "location": "지하1층", "type": "급배수", "status": "fault"},
        version=1,
    )
    # 관계 0인 고아 시설도 노드로 나와야 한다(OPTIONAL MATCH)
    await graph.merge_facility(
        tenant_id=tenant, pg_id=orphan, props={"name": "옥상탱크", "status": "normal"}, version=1
    )
    await graph.merge_incident(
        tenant_id=tenant,
        pg_id=incident,
        facility_id=facility,
        props={"symptom": "누수", "resolution": "패킹 교체", "occurred_at": "2026-07-01T00:00:00Z"},
        version=1,
        embedding=_vec(1),
    )
    await graph.merge_maintenance(
        tenant_id=tenant,
        pg_id=log_id,
        facility_id=facility,
        props={"work": "패킹 교체", "performed_at": "2026-07-02T00:00:00Z"},
        version=1,
    )

    result = await graph.fetch_facility_graph(tenant_id=tenant)

    by_id = {n.pg_id: n for n in result.nodes}
    assert set(by_id) == {facility, orphan, incident, log_id}
    pump = by_id[facility]
    assert (pump.label, pump.name, pump.type, pump.location, pump.status) == (
        "facility",
        "지하펌프",
        "급배수",
        "지하1층",
        "fault",
    )
    assert by_id[orphan].label == "facility"
    inc = by_id[incident]
    assert (inc.label, inc.name, inc.resolved) == ("incident", "누수", True)
    assert inc.at == "2026-07-01T00:00:00Z"
    maint = by_id[log_id]
    assert (maint.label, maint.name, maint.at) == (
        "maintenance",
        "패킹 교체",
        "2026-07-02T00:00:00Z",
    )
    # embedding은 어떤 노드에도 실리지 않는다(필드 자체가 없음 — 페이로드 폭발 차단)
    assert not any(hasattr(n, "embedding") for n in result.nodes)

    assert {(link.source, link.target, link.kind) for link in result.links} == {
        (facility, incident, "HAS_INCIDENT"),
        (facility, log_id, "HAS_MAINTENANCE"),
    }


async def test_fetch_facility_graph_isolates_other_tenant(graph: GraphClient) -> None:
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    facility_b = str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant_b, pg_id=facility_b, props={"name": "B펌프"}, version=1
    )
    await graph.merge_incident(
        tenant_id=tenant_b,
        pg_id=str(uuid.uuid4()),
        facility_id=facility_b,
        props={"symptom": "누수"},
        version=1,
    )

    result = await graph.fetch_facility_graph(tenant_id=tenant_a)

    assert result.nodes == ()
    assert result.links == ()


def _plan_props(
    *, unit_type_name: str = "84M", devices: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "unit_type_name": unit_type_name,
        "image_width": 923,
        "image_height": 676,
        "devices": devices if devices is not None else [],
    }


async def test_replace_floor_plan_creates_plan_and_devices(graph: GraphClient) -> None:
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    device_a, device_b = str(uuid.uuid4()), str(uuid.uuid4())
    props = _plan_props(
        devices=[
            {"pg_id": device_a, "device_type": "room", "x": 10, "y": 20, "room": "거실"},
            {"pg_id": device_b, "device_type": "콘센트", "x": 30, "y": 40, "dir": "left"},
        ]
    )

    await graph.replace_floor_plan(tenant_id=tenant, pg_id=pg_id, props=props, version=1)

    rows = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p, tenant_id:$t})-[:HAS_DEVICE]->(d:PlanDevice) "
        "RETURN fp.unit_type_name AS name, d.pg_id AS device_id, d.device_type AS device_type "
        "ORDER BY device_id",
        p=pg_id,
        t=tenant,
    )
    assert len(rows) == 2
    assert rows[0]["name"] == "84M"
    assert {r["device_id"] for r in rows} == {device_a, device_b}


async def test_replace_floor_plan_full_replace_idempotent(graph: GraphClient) -> None:
    """재적용해도 device 수가 늘지 않고, 이전 버전 device는 완전히 소멸한다(CRITICAL)."""
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    old_device = str(uuid.uuid4())
    await graph.replace_floor_plan(
        tenant_id=tenant,
        pg_id=pg_id,
        props=_plan_props(
            devices=[{"pg_id": old_device, "device_type": "room", "x": 1, "y": 1, "room": "방1"}]
        ),
        version=1,
    )

    new_device = str(uuid.uuid4())
    await graph.replace_floor_plan(
        tenant_id=tenant,
        pg_id=pg_id,
        props=_plan_props(
            devices=[{"pg_id": new_device, "device_type": "room", "x": 2, "y": 2, "room": "방2"}]
        ),
        version=2,
    )

    rows = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p})-[:HAS_DEVICE]->(d:PlanDevice) RETURN d.pg_id AS id",
        p=pg_id,
    )
    assert {r["id"] for r in rows} == {new_device}  # 옛 device 소멸, 새 device만 존재

    orphan = await _read(
        graph, "MATCH (d:PlanDevice {pg_id:$id}) RETURN count(*) AS c", id=old_device
    )
    assert orphan[0]["c"] == 0  # detach delete로 옛 노드 자체가 사라짐


async def test_replace_floor_plan_links_device_to_facility(graph: GraphClient) -> None:
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    device_id, facility_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.replace_floor_plan(
        tenant_id=tenant,
        pg_id=pg_id,
        props=_plan_props(
            devices=[
                {
                    "pg_id": device_id,
                    "device_type": "센서",
                    "x": 5,
                    "y": 5,
                    "facility_id": facility_id,
                }
            ]
        ),
        version=1,
    )

    rows = await _read(
        graph,
        "MATCH (d:PlanDevice {pg_id:$d})-[:LINKED_TO]->(f:Facility {pg_id:$f, tenant_id:$t}) "
        "RETURN count(*) AS c",
        d=device_id,
        f=facility_id,
        t=tenant,
    )
    assert rows[0]["c"] == 1


async def test_replace_floor_plan_cross_tenant_isolation(graph: GraphClient) -> None:
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    pg_id = str(uuid.uuid4())  # 우연히 동일 pg_id를 쓰더라도 tenant로 분리돼야 함
    device_a = str(uuid.uuid4())
    await graph.replace_floor_plan(
        tenant_id=tenant_a,
        pg_id=pg_id,
        props=_plan_props(
            unit_type_name="84M",
            devices=[{"pg_id": device_a, "device_type": "room", "x": 1, "y": 1}],
        ),
        version=1,
    )
    await graph.replace_floor_plan(
        tenant_id=tenant_b, pg_id=pg_id, props=_plan_props(unit_type_name="59C"), version=1
    )

    rows = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p, tenant_id:$t}) RETURN fp.unit_type_name AS name",
        p=pg_id,
        t=tenant_a,
    )
    assert rows[0]["name"] == "84M"  # tenant_b 갱신이 tenant_a 노드를 덮지 않음

    leak = await _read(
        graph, "MATCH (d:PlanDevice {pg_id:$d, tenant_id:$t}) RETURN count(*) AS c",
        d=device_a, t=tenant_b,
    )
    assert leak[0]["c"] == 0  # tenant_a의 device가 tenant_b에 노출되지 않음


async def test_merge_facility_tombstone_deletes_node_and_relations(graph: GraphClient) -> None:
    tenant, facility_id, incident_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant, pg_id=facility_id, props={"name": "펌프", "status": "fault"}, version=1
    )
    await graph.merge_incident(
        tenant_id=tenant,
        pg_id=incident_id,
        facility_id=facility_id,
        props={"symptom": "누수"},
        version=1,
    )

    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=facility_id,
        props={"deleted_at": "2026-07-27T00:00:00Z"},
        version=2,
    )

    rows = await _read(
        graph, "MATCH (f:Facility {pg_id:$p, tenant_id:$t}) RETURN f", p=facility_id, t=tenant
    )
    assert rows == []  # 노드 자체가 사라짐(관계 포함 detach delete)


async def test_fetch_facility_graph_include_plan_adds_plan_nodes(graph: GraphClient) -> None:
    tenant, facility_id = str(uuid.uuid4()), str(uuid.uuid4())
    plan_id, device_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant, pg_id=facility_id, props={"name": "정수기", "status": "normal"}, version=1
    )
    await graph.replace_floor_plan(
        tenant_id=tenant,
        pg_id=plan_id,
        props=_plan_props(
            devices=[
                {
                    "pg_id": device_id,
                    "device_type": "센서",
                    "x": 1,
                    "y": 1,
                    "room": "거실",
                    "facility_id": facility_id,
                }
            ]
        ),
        version=1,
    )

    default_result = await graph.fetch_facility_graph(tenant_id=tenant)
    assert plan_id not in {n.pg_id for n in default_result.nodes}  # 기본은 제외(과밀 방지)

    result = await graph.fetch_facility_graph(tenant_id=tenant, include_plan=True)
    by_id = {n.pg_id: n for n in result.nodes}
    assert by_id[plan_id].label == "floor_plan"
    assert by_id[device_id].label == "plan_device"
    assert {(link.source, link.target, link.kind) for link in result.links} >= {
        (plan_id, device_id, "HAS_DEVICE"),
        (device_id, facility_id, "LINKED_TO"),
    }


async def test_fetch_facility_graph_include_plan_handles_device_less_plan(
    graph: GraphClient,
) -> None:
    """마커 0개인 도면도 노드로는 나오되 HAS_DEVICE 관계는 없다."""
    tenant, plan_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.replace_floor_plan(
        tenant_id=tenant, pg_id=plan_id, props=_plan_props(unit_type_name="59C"), version=1
    )

    result = await graph.fetch_facility_graph(tenant_id=tenant, include_plan=True)

    assert {n.pg_id for n in result.nodes} == {plan_id}
    assert result.links == ()


async def test_maintenance_parts_create_replaced(graph: GraphClient) -> None:
    tenant, facility = str(uuid.uuid4()), str(uuid.uuid4())
    log_id = str(uuid.uuid4())

    await graph.merge_maintenance(
        tenant_id=tenant,
        pg_id=log_id,
        facility_id=facility,
        props={"work": "부품 교체", "performer": "김기사"},
        version=1,
        parts=[{"name": "베어링", "model": "BR-1"}, "필터"],
    )

    rows = await _read(
        graph,
        "MATCH (m:MaintenanceLog {pg_id:$m})-[:REPLACED]->(p:Part) "
        "RETURN p.name AS name, p.model AS model ORDER BY name",
        m=log_id,
    )
    parts = {r["name"]: r["model"] for r in rows}
    assert parts == {"베어링": "BR-1", "필터": None}
