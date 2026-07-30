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


async def test_merge_facility_creates_location_and_located_in(graph: GraphClient) -> None:
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=pg_id,
        props={"name": "펌프", "location": "101동", "status": "normal"},
        version=1,
    )

    rows = await _read(
        graph,
        "MATCH (f:Facility {pg_id:$p, tenant_id:$t})-[:LOCATED_IN]->(loc:Location) "
        "RETURN loc.name AS name, loc.tenant_id AS tenant_id",
        p=pg_id,
        t=tenant,
    )
    assert len(rows) == 1
    assert rows[0]["name"] == "101동"
    assert rows[0]["tenant_id"] == tenant


async def test_merge_facility_relocation_rewires_located_in(graph: GraphClient) -> None:
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant, pg_id=pg_id, props={"name": "펌프", "location": "101동"}, version=1
    )
    await graph.merge_facility(
        tenant_id=tenant, pg_id=pg_id, props={"name": "펌프", "location": "102동"}, version=2
    )

    rows = await _read(
        graph,
        "MATCH (f:Facility {pg_id:$p})-[:LOCATED_IN]->(loc:Location) RETURN loc.name AS name",
        p=pg_id,
    )
    assert [r["name"] for r in rows] == ["102동"]  # 옛 관계 소멸, 새 관계 1개만


async def test_merge_facility_null_location_removes_located_in(graph: GraphClient) -> None:
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant, pg_id=pg_id, props={"name": "펌프", "location": "101동"}, version=1
    )
    await graph.merge_facility(
        tenant_id=tenant, pg_id=pg_id, props={"name": "펌프", "location": None}, version=2
    )

    rows = await _read(
        graph,
        "MATCH (f:Facility {pg_id:$p})-[:LOCATED_IN]->(loc:Location) RETURN count(*) AS c",
        p=pg_id,
    )
    assert rows[0]["c"] == 0


async def test_merge_facility_location_cross_tenant_isolation(graph: GraphClient) -> None:
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    pg_a, pg_b = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant_a, pg_id=pg_a, props={"name": "A펌프", "location": "101동"}, version=1
    )
    await graph.merge_facility(
        tenant_id=tenant_b, pg_id=pg_b, props={"name": "B펌프", "location": "101동"}, version=1
    )

    rows = await _read(
        graph, "MATCH (loc:Location {name:$n}) RETURN loc.tenant_id AS tenant_id", n="101동"
    )
    assert {r["tenant_id"] for r in rows} == {tenant_a, tenant_b}  # 같은 이름, 분리된 노드

    leak = await _read(
        graph,
        "MATCH (f:Facility {pg_id:$p, tenant_id:$t})-[:LOCATED_IN]->(loc:Location) "
        "RETURN loc.tenant_id AS tenant_id",
        p=pg_a,
        t=tenant_a,
    )
    assert leak[0]["tenant_id"] == tenant_a


async def test_merge_facility_complex_via_location_chain(graph: GraphClient) -> None:
    """facility→loc→complex 체인 — location이 있으면 loc이 PART_OF, facility는 직결 안 함."""
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=pg_id,
        props={"name": "펌프", "location": "101동", "complex_name": "첫마을 4단지 푸르지오"},
        version=1,
    )

    rows = await _read(
        graph,
        "MATCH (f:Facility {pg_id:$p})-[:LOCATED_IN]->(loc:Location)-[:PART_OF]->"
        "(c:Complex {tenant_id:$t}) RETURN c.name AS name",
        p=pg_id,
        t=tenant,
    )
    assert rows[0]["name"] == "첫마을 4단지 푸르지오"

    direct = await _read(
        graph, "MATCH (f:Facility {pg_id:$p})-[:PART_OF]->(:Complex) RETURN count(*) AS c", p=pg_id
    )
    assert direct[0]["c"] == 0  # location 경유라 직결 없음


async def test_merge_facility_complex_direct_without_location(graph: GraphClient) -> None:
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=pg_id,
        props={"name": "펌프", "complex_name": "첫마을 4단지 푸르지오"},
        version=1,
    )

    rows = await _read(
        graph,
        "MATCH (f:Facility {pg_id:$p})-[:PART_OF]->(c:Complex {tenant_id:$t}) "
        "RETURN c.name AS name",
        p=pg_id,
        t=tenant,
    )
    assert rows[0]["name"] == "첫마을 4단지 푸르지오"


async def test_merge_facility_complex_tenant_isolation(graph: GraphClient) -> None:
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    pg_a, pg_b = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant_a, pg_id=pg_a, props={"name": "A펌프", "complex_name": "단지A"}, version=1
    )
    await graph.merge_facility(
        tenant_id=tenant_b, pg_id=pg_b, props={"name": "B펌프", "complex_name": "단지A"}, version=1
    )

    rows = await _read(
        graph, "MATCH (c:Complex {name:$n}) RETURN c.tenant_id AS tenant_id", n="단지A"
    )
    assert {r["tenant_id"] for r in rows} == {tenant_a, tenant_b}  # 이름 같아도 tenant별 분리 노드

    leak = await _read(
        graph,
        "MATCH (f:Facility {pg_id:$p, tenant_id:$t})-[:PART_OF]->(c:Complex) "
        "RETURN c.tenant_id AS tenant_id",
        p=pg_a,
        t=tenant_a,
    )
    assert leak[0]["tenant_id"] == tenant_a


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
    assert ctx.causal_chain == ()  # 인과 연쇄 없는 단독 장애
    # expand_incidents는 root_cause·resolution을 프로젝션하지 않는다(하위호환 — 브리프 §1)
    assert ctx.root_cause is None
    assert ctx.resolution is None


async def test_expand_incidents_empty_ids_returns_empty(graph: GraphClient) -> None:
    assert await graph.expand_incidents(tenant_id=str(uuid.uuid4()), pg_ids=[]) == []


async def test_incidents_for_facilities_returns_history_with_cause_and_resolution(
    graph: GraphClient,
) -> None:
    """facility 앵커로 HAS_INCIDENT 장애를 root_cause·resolution·인과 연쇄·최근 정비까지 확장.
    다른 facility의 장애는 섞이지 않는다(G2 §4.2)."""
    tenant = str(uuid.uuid4())
    fac_a, fac_b = str(uuid.uuid4()), str(uuid.uuid4())
    root, effect, inc_b = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant, pg_id=fac_a, props={"name": "급수펌프", "status": "normal"}, version=1
    )
    await graph.merge_facility(
        tenant_id=tenant, pg_id=fac_b, props={"name": "승강기", "status": "normal"}, version=1
    )
    # fac_a: 원인 장애 + 결과 장애(effect CAUSED_BY root), 조치 이력 포함
    await graph.merge_incident(
        tenant_id=tenant,
        pg_id=root,
        facility_id=fac_a,
        props={"symptom": "수위센서 오작동", "root_cause": "센서 노후", "resolution": "센서 교체"},
        version=1,
    )
    await graph.merge_incident(
        tenant_id=tenant,
        pg_id=effect,
        facility_id=fac_a,
        props={"symptom": "단수", "root_cause": "펌프 정지", "resolution": "펌프 재기동"},
        version=1,
        caused_by_incident_id=root,
    )
    await graph.merge_maintenance(
        tenant_id=tenant,
        pg_id=str(uuid.uuid4()),
        facility_id=fac_a,
        props={"work": "펌프 점검", "performed_at": "2026-01-01T00:00:00Z"},
        version=1,
    )
    # fac_b: 다른 설비 장애 — fac_a 조회 결과에 섞이면 안 됨
    await graph.merge_incident(
        tenant_id=tenant,
        pg_id=inc_b,
        facility_id=fac_b,
        props={"symptom": "도어 오작동", "root_cause": "센서 불량", "resolution": "센서 교체"},
        version=1,
    )

    contexts = await graph.incidents_for_facilities(tenant_id=tenant, facility_ids=[fac_a])

    by_id = {c.incident_id: c for c in contexts}
    assert set(by_id) == {root, effect}  # fac_b 장애 안 섞임
    assert by_id[effect].facility_name == "급수펌프"
    assert by_id[effect].root_cause == "펌프 정지"
    assert by_id[effect].resolution == "펌프 재기동"
    assert by_id[effect].causal_chain == ("수위센서 오작동",)  # CAUSED_BY 연쇄
    assert "펌프 점검" in by_id[effect].recent_work


async def test_incidents_for_facilities_empty_ids_returns_empty(graph: GraphClient) -> None:
    assert await graph.incidents_for_facilities(tenant_id=str(uuid.uuid4()), facility_ids=[]) == []


async def test_incidents_for_facilities_isolates_other_tenant(graph: GraphClient) -> None:
    """앵커 facility의 tenant를 강제 — 같은 pg_id를 타 tenant로 조회해도 노출 안 됨(격리)."""
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    facility = str(uuid.uuid4())  # 우연히 동일 pg_id를 두 tenant가 쓰더라도 분리돼야 함
    await graph.merge_facility(
        tenant_id=tenant_a, pg_id=facility, props={"name": "A펌프", "status": "fault"}, version=1
    )
    await graph.merge_incident(
        tenant_id=tenant_a,
        pg_id=str(uuid.uuid4()),
        facility_id=facility,
        props={"symptom": "누수"},
        version=1,
    )

    assert await graph.incidents_for_facilities(tenant_id=tenant_b, facility_ids=[facility]) == []


async def _merge_incident(
    graph: GraphClient,
    *,
    tenant: str,
    facility: str,
    pg_id: str,
    symptom: str,
    caused_by: str | None = None,
) -> None:
    await graph.merge_incident(
        tenant_id=tenant,
        pg_id=pg_id,
        facility_id=facility,
        props={"symptom": symptom},
        version=1,
        embedding=_vec(1),
        caused_by_incident_id=caused_by,
    )


async def test_merge_incident_creates_caused_by_edge(graph: GraphClient) -> None:
    """caused_by가 있으면 (결과)-[:CAUSED_BY]->(원인) 방향 엣지를 만든다(SEED-PLAN §1)."""
    tenant, facility = str(uuid.uuid4()), str(uuid.uuid4())
    cause, effect = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant, pg_id=facility, props={"name": "홈넷서버", "status": "fault"}, version=1
    )
    await _merge_incident(graph, tenant=tenant, facility=facility, pg_id=cause, symptom="서버 고장")
    await _merge_incident(
        graph,
        tenant=tenant,
        facility=facility,
        pg_id=effect,
        symptom="월패드 불능",
        caused_by=cause,
    )

    rows = await _read(
        graph,
        "MATCH (e:Incident {pg_id:$e, tenant_id:$t})-[:CAUSED_BY]->(c:Incident {pg_id:$c}) "
        "RETURN count(*) AS n",
        e=effect,
        c=cause,
        t=tenant,
    )
    assert rows[0]["n"] == 1


async def test_expand_incidents_returns_causal_chain(graph: GraphClient) -> None:
    """CAUSED_BY를 다단계(2 hop) 따라가 선행 원인들을 가까운 원인부터 반환한다."""
    tenant, facility = str(uuid.uuid4()), str(uuid.uuid4())
    root, mid, effect = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant, pg_id=facility, props={"name": "부스터펌프", "status": "fault"}, version=1
    )
    await _merge_incident(
        graph, tenant=tenant, facility=facility, pg_id=root, symptom="수위센서 오작동"
    )
    await _merge_incident(
        graph, tenant=tenant, facility=facility, pg_id=mid, symptom="펌프 진동", caused_by=root
    )
    await _merge_incident(
        graph, tenant=tenant, facility=facility, pg_id=effect, symptom="진동 재발", caused_by=mid
    )

    contexts = await graph.expand_incidents(tenant_id=tenant, pg_ids=[effect])

    assert len(contexts) == 1
    # effect → mid(1 hop) → root(2 hop): 가까운 원인부터
    assert contexts[0].causal_chain == ("펌프 진동", "수위센서 오작동")


async def test_expand_incidents_causal_chain_respects_hop_limit(graph: GraphClient) -> None:
    """3 hop 상한 — 4단계 깊이 연쇄는 3개까지만 반환하고 최말단은 제외한다."""
    tenant, facility = str(uuid.uuid4()), str(uuid.uuid4())
    ids = [str(uuid.uuid4()) for _ in range(5)]  # i0(결과) → i1 → i2 → i3 → i4(근원)
    await graph.merge_facility(
        tenant_id=tenant, pg_id=facility, props={"name": "수신반", "status": "fault"}, version=1
    )
    for depth, pg_id in enumerate(ids):
        caused_by = ids[depth + 1] if depth + 1 < len(ids) else None
        await _merge_incident(
            graph,
            tenant=tenant,
            facility=facility,
            pg_id=pg_id,
            symptom=f"단계{depth}",
            caused_by=caused_by,
        )

    contexts = await graph.expand_incidents(tenant_id=tenant, pg_ids=[ids[0]])

    chain = contexts[0].causal_chain
    assert chain == ("단계1", "단계2", "단계3")  # 3 hop까지, i4(단계4)는 제외


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
    assert set(by_id) == {facility, orphan, incident, log_id, "지하1층"}
    assert by_id["지하1층"].label == "location"
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
        (facility, "지하1층", "LOCATED_IN"),
    }


async def test_facility_code_round_trips_to_graph_node(graph: GraphClient) -> None:
    """시설 코드번호(H14-2)가 노드 프로퍼티로 저장되고 화면 조회에 실린다."""
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=pg_id,
        props={"name": "지하펌프", "code": "WT-1-01", "status": "normal"},
        version=1,
    )

    result = await graph.fetch_facility_graph(tenant_id=tenant)

    assert [n.code for n in result.nodes if n.label == "facility"] == ["WT-1-01"]


async def test_fetch_facility_graph_includes_location_node_and_link(
    graph: GraphClient,
) -> None:
    """Location·LOCATED_IN은 기본 그래프의 뼈대 — 항상 실린다(H13-7)."""
    tenant, facility_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=facility_id,
        props={"name": "지하펌프", "location": "지하1층", "status": "normal"},
        version=1,
    )

    result = await graph.fetch_facility_graph(tenant_id=tenant)

    locations = [n for n in result.nodes if n.label == "location"]
    assert len(locations) == 1
    assert locations[0].name == "지하1층"
    assert (facility_id, locations[0].pg_id, "LOCATED_IN") in {
        (link.source, link.target, link.kind) for link in result.links
    }


async def test_fetch_facility_graph_includes_complex_node_and_link(
    graph: GraphClient,
) -> None:
    """Complex(단지 루트)·PART_OF는 기본 그래프에 항상 실린다(H13-7)."""
    tenant, facility_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=facility_id,
        props={
            "name": "지하펌프",
            "location": "지하1층",
            "status": "normal",
            "complex_name": "첫마을 4단지 푸르지오",
        },
        version=1,
    )

    result = await graph.fetch_facility_graph(tenant_id=tenant)

    complexes = [n for n in result.nodes if n.label == "complex"]
    assert len(complexes) == 1
    assert complexes[0].name == "첫마을 4단지 푸르지오"
    locations = [n for n in result.nodes if n.label == "location"]
    # 체인: facility -[LOCATED_IN]-> location -[PART_OF]-> complex (직결 없음)
    assert (locations[0].pg_id, complexes[0].pg_id, "PART_OF") in {
        (link.source, link.target, link.kind) for link in result.links
    }
    assert (facility_id, complexes[0].pg_id, "PART_OF") not in {
        (link.source, link.target, link.kind) for link in result.links
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


async def test_replace_floor_plan_creates_room_and_kind_hubs(graph: GraphClient) -> None:
    """도면 → 방·종류 허브 → 마커 계층(H14-1 재구조화). room 타입 행은 PlanRoom으로 승격된다."""
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    room_row, marker_a, marker_b = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    props = _plan_props(
        devices=[
            {"pg_id": room_row, "device_type": "room", "x": 10, "y": 20, "room": "거실"},
            {"pg_id": marker_a, "device_type": "콘센트", "x": 30, "y": 40, "room": "거실"},
            {"pg_id": marker_b, "device_type": "스위치", "x": 50, "y": 60, "room": "거실"},
        ]
    )

    await graph.replace_floor_plan(tenant_id=tenant, pg_id=pg_id, props=props, version=1)

    rooms = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p, tenant_id:$t})-[:HAS_ROOM]->(r:PlanRoom) "
        "RETURN r.name AS name, r.plan_pg_id AS plan_pg_id",
        p=pg_id,
        t=tenant,
    )
    assert rooms == [{"name": "거실", "plan_pg_id": pg_id}]

    kinds = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p, tenant_id:$t})-[:HAS_KIND]->(k:PlanKind) "
        "RETURN k.name AS name ORDER BY name",
        p=pg_id,
        t=tenant,
    )
    assert [r["name"] for r in kinds] == ["스위치", "콘센트"]

    # room 타입 행은 마커로 남지 않는다(허브로 승격)
    markers = await _read(
        graph, "MATCH (d:PlanDevice {tenant_id:$t}) RETURN d.pg_id AS id ORDER BY id", t=tenant
    )
    assert {r["id"] for r in markers} == {marker_a, marker_b}

    # 체인: 도면 → 방 → 마커, 도면 → 종류 → 마커
    chain = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p, tenant_id:$t})-[:HAS_ROOM]->(:PlanRoom)"
        "-[:HAS_DEVICE]->(d:PlanDevice) "
        "RETURN d.pg_id AS id ORDER BY id",
        p=pg_id,
        t=tenant,
    )
    assert {r["id"] for r in chain} == {marker_a, marker_b}
    by_kind = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p, tenant_id:$t})-[:HAS_KIND]->(k:PlanKind)"
        "-[:HAS_DEVICE]->(d:PlanDevice) "
        "RETURN k.name AS kind, d.pg_id AS id ORDER BY kind",
        p=pg_id,
        t=tenant,
    )
    assert by_kind == [
        {"kind": "스위치", "id": marker_b},
        {"kind": "콘센트", "id": marker_a},
    ]


async def test_replace_floor_plan_marker_without_room_links_kind_only(graph: GraphClient) -> None:
    tenant, pg_id, marker = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await graph.replace_floor_plan(
        tenant_id=tenant,
        pg_id=pg_id,
        props=_plan_props(devices=[{"pg_id": marker, "device_type": "감지기", "x": 1, "y": 1}]),
        version=1,
    )

    rows = await _read(
        graph,
        "MATCH (d:PlanDevice {pg_id:$d})<-[:HAS_DEVICE]-(hub) "
        "RETURN labels(hub) AS labels, hub.name AS name",
        d=marker,
    )
    assert rows == [{"labels": ["PlanKind"], "name": "감지기"}]
    rooms = await _read(graph, "MATCH (r:PlanRoom {tenant_id:$t}) RETURN r.name AS n", t=tenant)
    assert rooms == []  # 방 정보가 없으면 방 허브를 발명하지 않는다


async def test_replace_floor_plan_full_replace_idempotent(graph: GraphClient) -> None:
    """재적용해도 허브·마커가 늘지 않고, 이전 버전 노드는 완전히 소멸한다(CRITICAL)."""
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    old_device = str(uuid.uuid4())
    old_snapshot = _plan_props(
        devices=[
            {"pg_id": str(uuid.uuid4()), "device_type": "room", "x": 1, "y": 1, "room": "방1"},
            {"pg_id": old_device, "device_type": "콘센트", "x": 1, "y": 1, "room": "방1"},
        ]
    )
    await graph.replace_floor_plan(tenant_id=tenant, pg_id=pg_id, props=old_snapshot, version=1)
    await graph.replace_floor_plan(
        tenant_id=tenant, pg_id=pg_id, props=old_snapshot, version=1
    )  # 같은 version 재실행 = no-op

    hubs = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p})-[:HAS_ROOM|HAS_KIND]->(hub) RETURN count(*) AS c",
        p=pg_id,
    )
    assert hubs[0]["c"] == 2  # 방1 + 콘센트, 중복 없음

    new_device = str(uuid.uuid4())
    await graph.replace_floor_plan(
        tenant_id=tenant,
        pg_id=pg_id,
        props=_plan_props(
            devices=[
                {"pg_id": str(uuid.uuid4()), "device_type": "room", "x": 2, "y": 2, "room": "방2"},
                {"pg_id": new_device, "device_type": "스위치", "x": 2, "y": 2, "room": "방2"},
            ]
        ),
        version=2,
    )

    rows = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p})-[:HAS_ROOM|HAS_KIND]->(hub)-[:HAS_DEVICE]->(d:PlanDevice) "
        "RETURN DISTINCT d.pg_id AS id",
        p=pg_id,
    )
    assert {r["id"] for r in rows} == {new_device}  # 옛 마커 소멸, 새 마커만 존재

    orphan = await _read(
        graph,
        "MATCH (n) WHERE (n:PlanDevice AND n.pg_id = $id) OR (n:PlanRoom AND n.name = '방1') "
        "OR (n:PlanKind AND n.name = '콘센트') RETURN count(*) AS c",
        id=old_device,
    )
    assert orphan[0]["c"] == 0  # detach delete로 옛 마커·허브가 함께 사라짐


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


async def test_replace_floor_plan_links_complex(graph: GraphClient) -> None:
    tenant, pg_id = str(uuid.uuid4()), str(uuid.uuid4())
    props = {**_plan_props(), "complex_name": "첫마을 4단지 푸르지오"}
    await graph.replace_floor_plan(tenant_id=tenant, pg_id=pg_id, props=props, version=1)

    rows = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p, tenant_id:$t})-[:PART_OF]->(c:Complex) "
        "RETURN c.name AS name",
        p=pg_id,
        t=tenant,
    )
    assert rows[0]["name"] == "첫마을 4단지 푸르지오"


async def test_replace_floor_plan_cross_tenant_isolation(graph: GraphClient) -> None:
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    pg_id = str(uuid.uuid4())  # 우연히 동일 pg_id를 쓰더라도 tenant로 분리돼야 함
    device_a = str(uuid.uuid4())
    await graph.replace_floor_plan(
        tenant_id=tenant_a,
        pg_id=pg_id,
        props=_plan_props(
            unit_type_name="84M",
            devices=[{"pg_id": device_a, "device_type": "콘센트", "x": 1, "y": 1, "room": "거실"}],
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
        graph,
        "MATCH (d:PlanDevice {pg_id:$d, tenant_id:$t}) RETURN count(*) AS c",
        d=device_a,
        t=tenant_b,
    )
    assert leak[0]["c"] == 0  # tenant_a의 device가 tenant_b에 노출되지 않음

    hub_leak = await _read(
        graph,
        "MATCH (fp:FloorPlan {pg_id:$p, tenant_id:$t})-[:HAS_ROOM|HAS_KIND]->(hub) "
        "RETURN count(*) AS c",
        p=pg_id,
        t=tenant_b,
    )
    assert hub_leak[0]["c"] == 0  # 방·종류 허브도 tenant_b 도면에 붙지 않음(CRITICAL)


async def test_merge_facility_tombstone_deletes_node_and_relations(graph: GraphClient) -> None:
    tenant, facility_id, incident_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant,
        pg_id=facility_id,
        props={"name": "펌프", "location": "101동", "status": "fault"},
        version=1,
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

    location_rel = await _read(
        graph,
        "MATCH (loc:Location {name:'101동', tenant_id:$t})<-[:LOCATED_IN]-() RETURN count(*) AS c",
        t=tenant,
    )
    assert location_rel[0]["c"] == 0  # LOCATED_IN도 detach delete로 함께 소멸


async def test_fetch_facility_graph_includes_plan_hierarchy(graph: GraphClient) -> None:
    """도면 → 방·종류 허브 → 마커가 모두 기본 표시된다(H14-1 재구조화 — 사용자 요청)."""
    tenant, facility_id = str(uuid.uuid4()), str(uuid.uuid4())
    plan_id, device_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.merge_facility(
        tenant_id=tenant, pg_id=facility_id, props={"name": "정수기", "status": "normal"}, version=1
    )
    await graph.replace_floor_plan(
        tenant_id=tenant,
        pg_id=plan_id,
        props={
            **_plan_props(
                devices=[
                    {
                        "pg_id": str(uuid.uuid4()),
                        "device_type": "room",
                        "x": 0,
                        "y": 0,
                        "room": "거실",
                    },
                    {
                        "pg_id": device_id,
                        "device_type": "센서",
                        "x": 1,
                        "y": 1,
                        "room": "거실",
                        "facility_id": facility_id,
                    },
                ]
            ),
            "complex_name": "첫마을 4단지 푸르지오",
        },
        version=1,
    )

    result = await graph.fetch_facility_graph(tenant_id=tenant)

    by_id = {n.pg_id: n for n in result.nodes}
    assert by_id[plan_id].label == "floor_plan"
    assert by_id[plan_id].name == "84M"
    room_id, kind_id = f"{plan_id}:room:거실", f"{plan_id}:kind:센서"
    assert (by_id[room_id].label, by_id[room_id].name) == ("plan_room", "거실")
    assert (by_id[kind_id].label, by_id[kind_id].name) == ("plan_kind", "센서")
    assert by_id[device_id].label == "plan_device"
    assert by_id[device_id].name == "센서(거실)"

    edges = {(link.source, link.target, link.kind) for link in result.links}
    assert (plan_id, room_id, "HAS_ROOM") in edges
    assert (plan_id, kind_id, "HAS_KIND") in edges
    assert (room_id, device_id, "HAS_DEVICE") in edges
    assert (kind_id, device_id, "HAS_DEVICE") in edges
    assert (device_id, facility_id, "LINKED_TO") in edges
    # 도면發 PART_OF는 도면이 기본 표시라 항상 포함(dangling 아님)
    assert (plan_id, "첫마을 4단지 푸르지오", "PART_OF") in edges


async def test_prune_floor_plans_deletes_stale_plans_with_hubs_and_devices(
    graph: GraphClient,
) -> None:
    """keep 목록 밖 도면은 하위 허브·마커까지 삭제, keep 도면은 보존(H14-1 잔존 노드 정리)."""
    tenant = str(uuid.uuid4())
    keep_id, stale_id = str(uuid.uuid4()), str(uuid.uuid4())
    keep_device, stale_device = str(uuid.uuid4()), str(uuid.uuid4())
    for plan_id, device_id in ((keep_id, keep_device), (stale_id, stale_device)):
        await graph.replace_floor_plan(
            tenant_id=tenant,
            pg_id=plan_id,
            props=_plan_props(
                devices=[
                    {
                        "pg_id": str(uuid.uuid4()),
                        "device_type": "room",
                        "x": 1,
                        "y": 1,
                        "room": "안방",
                    },
                    {"pg_id": device_id, "device_type": "콘센트", "x": 1, "y": 1, "room": "안방"},
                ]
            ),
            version=1,
        )

    deleted = await graph.prune_floor_plans(tenant_id=tenant, keep_pg_ids=[keep_id])

    assert deleted == 1
    plans = await _read(
        graph, "MATCH (fp:FloorPlan {tenant_id:$t}) RETURN fp.pg_id AS id", t=tenant
    )
    assert [r["id"] for r in plans] == [keep_id]
    devices = await _read(
        graph, "MATCH (d:PlanDevice {tenant_id:$t}) RETURN d.pg_id AS id", t=tenant
    )
    assert [r["id"] for r in devices] == [keep_device]
    hubs = await _read(
        graph,
        "MATCH (hub) WHERE (hub:PlanRoom OR hub:PlanKind) AND hub.tenant_id = $t "
        "RETURN DISTINCT hub.plan_pg_id AS plan_id",
        t=tenant,
    )
    assert [r["plan_id"] for r in hubs] == [keep_id]  # 허브도 도면과 함께 사라짐


async def test_prune_floor_plans_isolates_other_tenant(graph: GraphClient) -> None:
    """타 tenant 도면은 keep 목록에 없어도 불가침(CRITICAL — 격리)."""
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    plan_b, device_b = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.replace_floor_plan(
        tenant_id=tenant_b,
        pg_id=plan_b,
        props=_plan_props(
            devices=[{"pg_id": device_b, "device_type": "콘센트", "x": 1, "y": 1, "room": "안방"}]
        ),
        version=1,
    )

    # keep 빈 목록 = tenant_a의 도면 전부 삭제 의도 — 남의 tenant까지 번지면 안 된다
    deleted = await graph.prune_floor_plans(tenant_id=tenant_a, keep_pg_ids=[])

    assert deleted == 0
    rows = await _read(
        graph,
        "MATCH (fp:FloorPlan {tenant_id:$t})-[:HAS_ROOM|HAS_KIND]->(hub)"
        "-[:HAS_DEVICE]->(d:PlanDevice) "
        "RETURN DISTINCT fp.pg_id AS plan_id, d.pg_id AS device_id",
        t=tenant_b,
    )
    assert rows == [{"plan_id": plan_b, "device_id": device_b}]


async def test_prune_floor_plans_empty_keep_clears_tenant(graph: GraphClient) -> None:
    """keep이 비면 해당 tenant 도면을 전부 지운다(PG에 도면 0건인 경우의 정리)."""
    tenant, plan_id = str(uuid.uuid4()), str(uuid.uuid4())
    await graph.replace_floor_plan(tenant_id=tenant, pg_id=plan_id, props=_plan_props(), version=1)

    deleted = await graph.prune_floor_plans(tenant_id=tenant, keep_pg_ids=[])

    assert deleted == 1
    rows = await _read(graph, "MATCH (fp:FloorPlan {tenant_id:$t}) RETURN fp", t=tenant)
    assert rows == []


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
