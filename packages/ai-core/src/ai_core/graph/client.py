"""Neo4j typed query 레이어 — 시설 그래프 MERGE·검색 (docs/11 §4).

**격리 강제(구조)**: raw Cypher 실행 경로를 모듈 밖으로 열지 않는다. 노출하는 것은
tenant predicate를 구조적으로 포함하는 typed 메서드뿐이다(코드 리뷰가 아니라 쿼리
구조로 cross-tenant를 차단). 관계 생성 시 양 끝 노드를 **같은 $tenant 바인딩**으로
MERGE하므로 다른 tenant 노드에 붙는 관계가 구조적으로 만들어질 수 없다.

**역전 방지**: 노드는 `last_applied_version`을 보유하고, 들어온 sequence가 저장값
이하이면 프로퍼티를 쓰지 않는다(멱등 + 순서 역전 차단, docs/03 §4.9).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from ai_core.graph.config import GraphSettings, get_graph_settings

# pgvector content_chunks와 동일 모델·차원(bge-m3, cosine) — docs/11 §5
EMBEDDING_DIMENSIONS = 1024
# db.index.vector.queryNodes는 전역 top-K 후 tenant 필터 → 여유 배수로 뽑아 recall 보전
_SEARCH_OVERSAMPLE = 5
_DATABASE = "neo4j"


@dataclass(frozen=True)
class IncidentHit:
    pg_id: str
    symptom: str
    score: float


@dataclass(frozen=True)
class GraphNode:
    """화면용 그래프 노드(H13-1). 라벨별로 채워지는 필드가 다르다.

    `embedding`은 절대 담지 않는다 — 반환 프로퍼티를 Cypher에서 열거해 구조적으로 차단
    (수천 float 페이로드 + 규칙 7 토큰/전송 비용).
    """

    pg_id: str
    label: str  # facility | incident | maintenance | floor_plan | plan_device (H13-6)
    name: str | None = None  # facility.name | incident.symptom | maintenance.work |
    # floor_plan.unit_type_name | plan_device.device_type(+room)
    type: str | None = None  # facility.type (계통 렌즈)
    location: str | None = None  # facility.location (위치 렌즈, H13-2)
    status: str | None = None  # facility.status
    at: str | None = None  # incident.occurred_at | maintenance.performed_at
    resolved: bool | None = None  # incident: resolution 유무


@dataclass(frozen=True)
class GraphLink:
    source: str  # facility | floor_plan pg_id
    target: str  # incident | maintenance | plan_device | facility pg_id
    kind: str  # HAS_INCIDENT | HAS_MAINTENANCE | HAS_DEVICE | LINKED_TO (H13-6)


@dataclass(frozen=True)
class FacilityGraph:
    nodes: tuple[GraphNode, ...]
    links: tuple[GraphLink, ...]


@dataclass(frozen=True)
class IncidentContext:
    """장애 이웃 확장 결과 — 소속 시설·최근 정비(H3-3 search_facility_graph)."""

    incident_id: str
    symptom: str
    facility_name: str | None
    facility_status: str | None
    recent_work: tuple[str, ...]


class GraphClient:
    """시설 그래프 접근점. 드라이버 주입으로 테스트(Neo4jContainer)."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    @classmethod
    def from_settings(cls, settings: GraphSettings | None = None) -> GraphClient:
        cfg = settings or get_graph_settings()
        driver = AsyncGraphDatabase.driver(cfg.neo4j_uri, auth=(cfg.neo4j_user, cfg.neo4j_password))
        return cls(driver)

    async def close(self) -> None:
        await self._driver.close()

    async def _run(self, cypher: str, params: Mapping[str, Any]) -> list[Any]:
        result = await self._driver.execute_query(cypher, dict(params), database_=_DATABASE)
        return list(result.records)

    # ── 스키마 ──────────────────────────────────────────────────────────

    async def ensure_constraints_and_index(self) -> None:
        """노드별 (pg_id, tenant_id) 유니크 제약 + incident 벡터 인덱스. 멱등(IF NOT EXISTS)."""
        for label in ("Facility", "Incident", "MaintenanceLog", "FloorPlan", "PlanDevice"):
            await self._run(
                f"CREATE CONSTRAINT {label.lower()}_pg_tenant IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE (n.pg_id, n.tenant_id) IS UNIQUE",
                {},
            )
        # Part는 pg_id가 없다(JSONB 임베디드) — (tenant_id, name)이 키
        await self._run(
            "CREATE CONSTRAINT part_tenant_name IF NOT EXISTS "
            "FOR (n:Part) REQUIRE (n.tenant_id, n.name) IS UNIQUE",
            {},
        )
        await self._run(
            "CREATE VECTOR INDEX incident_embedding IF NOT EXISTS "
            "FOR (i:Incident) ON (i.embedding) "
            "OPTIONS { indexConfig: { "
            "`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine' } }",
            {"dim": EMBEDDING_DIMENSIONS},
        )
        # 벡터 인덱스 생성은 비동기 — 검색 전 온라인 대기
        await self._run("CALL db.awaitIndexes()", {})

    # ── MERGE (역전 방지 + tenant 구조 강제) ────────────────────────────

    async def merge_facility(
        self, *, tenant_id: str, pg_id: str, props: Mapping[str, Any], version: int
    ) -> None:
        """시설 upsert. `props.deleted_at`이 truthy면 tombstone — 노드를 관계까지 완전 삭제한다
        (facilities.py의 소프트 삭제 스냅샷 계약, H13-6). 삭제는 순서 역전 가드 없이 즉시 반영
        — 삭제 후 재작성 레이스는 이 파일럿 범위 밖
        (ponytail: 재정렬 필요해지면 version 가드 추가)."""
        if props.get("deleted_at"):
            await self._run(
                "MATCH (f:Facility {pg_id: $pg_id, tenant_id: $tenant}) DETACH DELETE f",
                {"pg_id": pg_id, "tenant": tenant_id},
            )
            return
        await self._run(
            "MERGE (f:Facility {pg_id: $pg_id, tenant_id: $tenant}) "
            "ON CREATE SET f.last_applied_version = -1 "
            "WITH f WHERE $version > f.last_applied_version "
            "SET f.name = $name, f.location = $location, f.type = $type, "
            "    f.status = $status, f.last_applied_version = $version",
            {
                "pg_id": pg_id,
                "tenant": tenant_id,
                "version": version,
                "name": props.get("name"),
                "location": props.get("location"),
                "type": props.get("type"),
                "status": props.get("status"),
            },
        )

    async def merge_incident(
        self,
        *,
        tenant_id: str,
        pg_id: str,
        facility_id: str,
        props: Mapping[str, Any],
        version: int,
        embedding: Sequence[float] | None = None,
    ) -> None:
        # facility·incident를 같은 $tenant로 MERGE → cross-tenant 관계 구조적 불가.
        # facility 노드가 아직 없으면 stub(props는 후속 facility 이벤트가 채움).
        await self._run(
            "MERGE (f:Facility {pg_id: $facility_id, tenant_id: $tenant}) "
            "ON CREATE SET f.last_applied_version = -1 "
            "MERGE (i:Incident {pg_id: $pg_id, tenant_id: $tenant}) "
            "ON CREATE SET i.last_applied_version = -1 "
            "MERGE (f)-[:HAS_INCIDENT]->(i) "
            "WITH i WHERE $version > i.last_applied_version "
            "SET i.symptom = $symptom, i.resolution = $resolution, "
            "    i.occurred_at = $occurred_at, i.root_cause = $root_cause, "
            "    i.last_applied_version = $version "
            "FOREACH (_ IN CASE WHEN $embedding IS NULL THEN [] ELSE [1] END | "
            "    SET i.embedding = $embedding)",
            {
                "pg_id": pg_id,
                "facility_id": facility_id,
                "tenant": tenant_id,
                "version": version,
                "symptom": props.get("symptom"),
                "resolution": props.get("resolution"),
                "occurred_at": props.get("occurred_at"),
                "root_cause": props.get("root_cause"),
                "embedding": list(embedding) if embedding is not None else None,
            },
        )

    async def merge_maintenance(
        self,
        *,
        tenant_id: str,
        pg_id: str,
        facility_id: str,
        props: Mapping[str, Any],
        version: int,
        parts: Any = None,
    ) -> None:
        await self._run(
            "MERGE (f:Facility {pg_id: $facility_id, tenant_id: $tenant}) "
            "ON CREATE SET f.last_applied_version = -1 "
            "MERGE (m:MaintenanceLog {pg_id: $pg_id, tenant_id: $tenant}) "
            "ON CREATE SET m.last_applied_version = -1 "
            "MERGE (f)-[:HAS_MAINTENANCE]->(m) "
            "WITH m WHERE $version > m.last_applied_version "
            "SET m.work = $work, m.performed_at = $performed_at, "
            "    m.performer = $performer, m.last_applied_version = $version "
            "WITH m "
            "UNWIND $parts AS part "
            "MERGE (p:Part {tenant_id: $tenant, name: part.name}) "
            "SET p.model = part.model "
            "MERGE (m)-[:REPLACED]->(p)",
            {
                "pg_id": pg_id,
                "facility_id": facility_id,
                "tenant": tenant_id,
                "version": version,
                "work": props.get("work"),
                "performed_at": props.get("performed_at"),
                "performer": props.get("performer"),
                "parts": _normalize_parts(parts),
            },
        )

    async def replace_floor_plan(
        self, *, tenant_id: str, pg_id: str, props: Mapping[str, Any], version: int
    ) -> None:
        """평면도 도면 upsert + 마커(`PlanDevice`) 전체 교체(H13-6, docs/03 §4.9 floor_plan 스냅샷).

        PG `plan_devices`는 항상 delete-then-insert 전체교체라 그래프도 동일 정책 —
        기존 `HAS_DEVICE` 대상 전부 detach delete 후 스냅샷으로 재생성한다. `facility_id`가
        있는 마커는 `LINKED_TO`로 Facility에 연결(merge_incident 관례와 동일 stub 허용).
        """
        devices = [dict(d) for d in props.get("devices") or []]
        await self._run(
            "MERGE (fp:FloorPlan {pg_id: $pg_id, tenant_id: $tenant}) "
            "ON CREATE SET fp.last_applied_version = -1 "
            "WITH fp WHERE $version > fp.last_applied_version "
            "SET fp.unit_type_name = $unit_type_name, fp.image_width = $image_width, "
            "    fp.image_height = $image_height, fp.last_applied_version = $version "
            "WITH fp "
            "OPTIONAL MATCH (fp)-[:HAS_DEVICE]->(old:PlanDevice) "
            "DETACH DELETE old "
            "WITH DISTINCT fp "
            "UNWIND $devices AS device "
            "CREATE (d:PlanDevice {pg_id: device.pg_id, tenant_id: $tenant}) "
            "SET d.device_type = device.device_type, d.x = device.x, d.y = device.y, "
            "    d.room = device.room, d.dir = device.dir, d.label = device.label "
            "MERGE (fp)-[:HAS_DEVICE]->(d) "
            "WITH d, device "
            "FOREACH (_ IN CASE WHEN device.facility_id IS NULL THEN [] ELSE [1] END | "
            "    MERGE (f:Facility {pg_id: device.facility_id, tenant_id: $tenant}) "
            "    ON CREATE SET f.last_applied_version = -1 "
            "    MERGE (d)-[:LINKED_TO]->(f))",
            {
                "pg_id": pg_id,
                "tenant": tenant_id,
                "version": version,
                "unit_type_name": props.get("unit_type_name"),
                "image_width": props.get("image_width"),
                "image_height": props.get("image_height"),
                "devices": devices,
            },
        )

    # ── 검색 (H3-3 재사용, 이번엔 격리 테스트용) ────────────────────────

    async def search_incidents(
        self, *, tenant_id: str, query_vector: Sequence[float], k: int
    ) -> list[IncidentHit]:
        records = await self._run(
            "CALL db.index.vector.queryNodes('incident_embedding', $fetch_k, $query_vector) "
            "YIELD node, score "
            "WHERE node.tenant_id = $tenant "
            "RETURN node.pg_id AS pg_id, node.symptom AS symptom, score "
            "ORDER BY score DESC LIMIT $k",
            {
                "tenant": tenant_id,
                "query_vector": list(query_vector),
                "fetch_k": k * _SEARCH_OVERSAMPLE,
                "k": k,
            },
        )
        return [
            IncidentHit(pg_id=r["pg_id"], symptom=r["symptom"], score=r["score"]) for r in records
        ]

    async def expand_incidents(
        self, *, tenant_id: str, pg_ids: Sequence[str]
    ) -> list[IncidentContext]:
        """장애들의 이웃(소속 시설·상태 + 최근 정비 작업 3건) 확장. tenant 구조 강제."""
        if not pg_ids:
            return []
        records = await self._run(
            "MATCH (f:Facility {tenant_id: $tenant})-[:HAS_INCIDENT]->(i:Incident) "
            "WHERE i.pg_id IN $ids "
            "OPTIONAL MATCH (f)-[:HAS_MAINTENANCE]->(m:MaintenanceLog) "
            "WITH i, f, m ORDER BY m.performed_at DESC "
            "RETURN i.pg_id AS incident_id, i.symptom AS symptom, "
            "       f.name AS facility_name, f.status AS facility_status, "
            "       [w IN collect(m.work) WHERE w IS NOT NULL][..3] AS recent_work",
            {"tenant": tenant_id, "ids": list(pg_ids)},
        )
        return [
            IncidentContext(
                incident_id=r["incident_id"],
                symptom=r["symptom"],
                facility_name=r["facility_name"],
                facility_status=r["facility_status"],
                recent_work=tuple(r["recent_work"]),
            )
            for r in records
        ]

    # ── 화면 조회 (H13-1 — 시설 그래프 메인의 유일한 읽기 경로) ─────────────

    async def fetch_facility_graph(
        self, *, tenant_id: str, include_plan: bool = False
    ) -> FacilityGraph:
        """단지 시설 그래프 전체(노드 + 관계). 관계 0인 고아 시설도 노드로 포함.

        tenant는 시설·이웃 양쪽에 강제한다. 반환 프로퍼티는 열거식 —
        `embedding`은 결과에 들어갈 수 없다(페이로드 폭발 방지, ADR-0022).

        `include_plan=True`면 평면도·마커(FloorPlan·PlanDevice)도 실어 반환한다(H13-6) —
        마커가 단지 전체 시설 대비 훨씬 많아(도면당 수십개) 기본은 제외, 화면이 opt-in.
        """
        records = await self._run(
            "MATCH (f:Facility {tenant_id: $tenant}) "
            "OPTIONAL MATCH (f)-[r:HAS_INCIDENT|HAS_MAINTENANCE]->(n) "
            "WHERE n.tenant_id = $tenant "
            "RETURN f.pg_id AS facility_id, f.name AS facility_name, f.type AS facility_type, "
            "       f.location AS facility_location, f.status AS facility_status, "
            "       type(r) AS kind, n.pg_id AS node_id, "
            "       n.symptom AS symptom, n.occurred_at AS occurred_at, "
            "       n.resolution IS NOT NULL AS resolved, "
            "       n.work AS work, n.performed_at AS performed_at "
            "ORDER BY facility_name, node_id",
            {"tenant": tenant_id},
        )
        nodes: dict[str, GraphNode] = {}
        links: list[GraphLink] = []
        for r in records:
            facility_id = r["facility_id"]
            if facility_id not in nodes:
                nodes[facility_id] = GraphNode(
                    pg_id=facility_id,
                    label="facility",
                    name=r["facility_name"],
                    type=r["facility_type"],
                    location=r["facility_location"],
                    status=r["facility_status"],
                )
            kind, node_id = r["kind"], r["node_id"]
            if kind is None or node_id is None:  # 고아 시설(관계 0)
                continue
            if node_id not in nodes:
                nodes[node_id] = _neighbor_node(kind, node_id, r)
            links.append(GraphLink(source=facility_id, target=node_id, kind=kind))

        if include_plan:
            await self._merge_plan_graph(tenant_id=tenant_id, nodes=nodes, links=links)

        return FacilityGraph(nodes=tuple(nodes.values()), links=tuple(links))

    async def _merge_plan_graph(
        self, *, tenant_id: str, nodes: dict[str, GraphNode], links: list[GraphLink]
    ) -> None:
        """평면도·마커 노드/관계를 fetch_facility_graph 결과에 덧붙인다(include_plan=True 전용)."""
        records = await self._run(
            "MATCH (fp:FloorPlan {tenant_id: $tenant}) "
            "OPTIONAL MATCH (fp)-[:HAS_DEVICE]->(d:PlanDevice) "
            "OPTIONAL MATCH (d)-[:LINKED_TO]->(f:Facility {tenant_id: $tenant}) "
            "RETURN fp.pg_id AS plan_id, fp.unit_type_name AS unit_type_name, "
            "       d.pg_id AS device_id, d.device_type AS device_type, d.room AS room, "
            "       f.pg_id AS facility_id "
            "ORDER BY unit_type_name, device_id",
            {"tenant": tenant_id},
        )
        for r in records:
            plan_id = r["plan_id"]
            if plan_id not in nodes:
                nodes[plan_id] = GraphNode(
                    pg_id=plan_id, label="floor_plan", name=r["unit_type_name"]
                )
            device_id = r["device_id"]
            if device_id is None:  # 마커 0개인 도면
                continue
            if device_id not in nodes:
                name = r["device_type"] if not r["room"] else f"{r['device_type']}({r['room']})"
                nodes[device_id] = GraphNode(pg_id=device_id, label="plan_device", name=name)
            links.append(GraphLink(source=plan_id, target=device_id, kind="HAS_DEVICE"))
            facility_id = r["facility_id"]
            if facility_id is not None:
                links.append(GraphLink(source=device_id, target=facility_id, kind="LINKED_TO"))


def _neighbor_node(kind: str, node_id: str, record: Any) -> GraphNode:
    if kind == "HAS_INCIDENT":
        return GraphNode(
            pg_id=node_id,
            label="incident",
            name=record["symptom"],
            at=_as_text(record["occurred_at"]),
            resolved=bool(record["resolved"]),
        )
    return GraphNode(
        pg_id=node_id,
        label="maintenance",
        name=record["work"],
        at=_as_text(record["performed_at"]),
    )


def _as_text(value: Any) -> str | None:
    """시각 프로퍼티는 outbox JSON 스냅샷 유래(문자열)지만 방어적으로 문자열화."""
    return None if value is None else str(value)


def _normalize_parts(parts: Any) -> list[dict[str, Any]]:
    """parts(JSONB: list 또는 dict)를 [{name, model?}] 로 정규화. 비면 []."""
    if not parts:
        return []
    items: Any = parts
    if isinstance(parts, dict):
        if isinstance(parts.get("items"), list):
            items = parts["items"]
        elif parts.get("name"):
            items = [parts]
        else:  # name→model 매핑으로 간주
            items = [{"name": k, "model": v} for k, v in parts.items()]
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            result.append({"name": item, "model": None})
        elif isinstance(item, dict) and item.get("name"):
            result.append({"name": item["name"], "model": item.get("model")})
    return result
