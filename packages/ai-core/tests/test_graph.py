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
