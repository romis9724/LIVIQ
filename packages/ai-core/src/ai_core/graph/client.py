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
# plan_devices 스냅샷에서 '방 자체'를 뜻하는 device_type — 마커가 아니라 방 허브로 승격한다(H14-1)
_ROOM_DEVICE_TYPE = "room"


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
    # facility | incident | maintenance | floor_plan | plan_device (H13-6)
    # | location | complex (H13-7 — 단지 루트) | plan_room | plan_kind (H14-1 — 도면 하위 허브)
    label: str
    name: str | None = None  # facility.name | incident.symptom | maintenance.work |
    # floor_plan.unit_type_name | plan_device.device_type(+room) | location.name | complex.name |
    # plan_room.name(방) | plan_kind.name(마커 종류)
    code: str | None = None  # facility.code — 시설 코드번호(H14-2)
    type: str | None = None  # facility.type (계통 렌즈)
    location: str | None = None  # facility.location (위치 렌즈, H13-2)
    status: str | None = None  # facility.status
    at: str | None = None  # incident.occurred_at | maintenance.performed_at
    resolved: bool | None = None  # incident: resolution 유무


@dataclass(frozen=True)
class GraphLink:
    source: str  # facility | floor_plan pg_id | plan_room·plan_kind 합성 id
    target: str  # incident | maintenance | plan_device | facility pg_id
    # HAS_INCIDENT | HAS_MAINTENANCE | HAS_DEVICE | LINKED_TO (H13-6)
    # | LOCATED_IN | PART_OF (H13-7) | HAS_ROOM | HAS_KIND (H14-1)
    kind: str


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
        # Part·Location은 pg_id가 없다(PG 원 컬럼값 유래) — (tenant_id, name)이 키
        await self._run(
            "CREATE CONSTRAINT part_tenant_name IF NOT EXISTS "
            "FOR (n:Part) REQUIRE (n.tenant_id, n.name) IS UNIQUE",
            {},
        )
        await self._run(
            "CREATE CONSTRAINT location_tenant_name IF NOT EXISTS "
            "FOR (n:Location) REQUIRE (n.tenant_id, n.name) IS UNIQUE",
            {},
        )
        # Complex는 단지당 1개 — tenant_id 단독 키(단지 루트 노드, H13-7)
        await self._run(
            "CREATE CONSTRAINT complex_tenant IF NOT EXISTS "
            "FOR (n:Complex) REQUIRE n.tenant_id IS UNIQUE",
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
        (ponytail: 재정렬 필요해지면 version 가드 추가).

        `location`이 비어있지 않으면 `(:Location {name, tenant_id})`를 실체화해
        `(f)-[:LOCATED_IN]->(loc)`로 잇는다(docs/11 §4 원 모델 복원, H13-7 —
        위치는 화면이 발명하는 가상 허브가 아니라 그래프 실체). 위치가 바뀌면 옛
        LOCATED_IN을 먼저 제거하고 새로 연결하고, null/빈 문자열이면 관계만 제거한다.
        재배선은 버전 가드 통과(실제 갱신) 시에만 일어난다. 참조 없는 고아 Location
        정리는 하지 않음(ponytail: 시각 노이즈 아님 — 수요 생기면 후속).

        `complex_name`이 비어있지 않으면 단지 루트 `(:Complex {tenant_id})`를 실체화한다
        (사용자 요청 — 그래프 중심에 단지 노드). 위치가 있으면 `(loc)-[:PART_OF]->(complex)`,
        없으면 `(f)-[:PART_OF]->(complex)` 직접 연결. Complex는 tenant당 1개라 위치 쪽 연결은
        재배선이 필요 없고(같은 노드로 계속 MERGE), 시설 직결만 옛 관계를 지우고 다시 잇는다."""
        if props.get("deleted_at"):
            await self._run(
                "MATCH (f:Facility {pg_id: $pg_id, tenant_id: $tenant}) DETACH DELETE f",
                {"pg_id": pg_id, "tenant": tenant_id},
            )
            return
        location = props.get("location")
        complex_name = props.get("complex_name")
        applied = await self._run(
            "MERGE (f:Facility {pg_id: $pg_id, tenant_id: $tenant}) "
            "ON CREATE SET f.last_applied_version = -1 "
            "WITH f WHERE $version > f.last_applied_version "
            "SET f.name = $name, f.code = $code, f.location = $location, f.type = $type, "
            "    f.status = $status, f.last_applied_version = $version "
            "WITH f "
            "OPTIONAL MATCH (f)-[old:LOCATED_IN]->(:Location) "
            "DELETE old "
            "WITH DISTINCT f "
            "FOREACH (_ IN CASE WHEN $location IS NULL OR $location = '' THEN [] ELSE [1] END | "
            "    MERGE (loc:Location {name: $location, tenant_id: $tenant}) "
            "    MERGE (f)-[:LOCATED_IN]->(loc)) "
            "WITH DISTINCT f "
            "OPTIONAL MATCH (f)-[old2:PART_OF]->(:Complex) "
            "DELETE old2 "
            "RETURN f.pg_id AS pg_id",
            {
                "pg_id": pg_id,
                "tenant": tenant_id,
                "version": version,
                "name": props.get("name"),
                "code": props.get("code"),
                "location": location,
                "type": props.get("type"),
                "status": props.get("status"),
            },
        )
        if applied and complex_name:
            await self._run(
                "MATCH (f:Facility {pg_id: $pg_id, tenant_id: $tenant}) "
                "MERGE (c:Complex {tenant_id: $tenant}) "
                "SET c.name = $complex_name "
                "WITH f, c "
                "OPTIONAL MATCH (f)-[:LOCATED_IN]->(loc:Location) "
                "FOREACH (_ IN CASE WHEN loc IS NULL THEN [1] ELSE [] END | "
                "    MERGE (f)-[:PART_OF]->(c)) "
                "FOREACH (_ IN CASE WHEN loc IS NULL THEN [] ELSE [1] END | "
                "    MERGE (loc)-[:PART_OF]->(c))",
                {"pg_id": pg_id, "tenant": tenant_id, "complex_name": complex_name},
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
        """평면도 도면 upsert + 하위 그래프 전체 교체(H13-6, docs/03 §4.9 floor_plan 스냅샷).

        **계층(H14-1 재구조화 — 사용자 요청)**: 도면 → 방·종류 허브 → 마커.
        `device_type='room'`인 스냅샷 항목은 마커가 아니라 방 자체라 `(:PlanRoom)` 허브로
        승격하고(`HAS_ROOM`), 나머지 요소의 distinct `device_type`은 `(:PlanKind)` 허브가
        된다(`HAS_KIND`). 마커(`:PlanDevice`)는 도면에 직결하지 않고 자기 방·자기 종류
        허브에서 각각 `HAS_DEVICE`로 내려온다(방 정보가 없는 마커는 종류 허브에만 달린다) —
        화면이 가상 허브를 발명하지 않도록 그래프에 실체화한다(ADR-0022, H13-7 교훈).

        PG `plan_devices`는 항상 delete-then-insert 전체교체라 그래프도 동일 정책 —
        기존 하위 노드(허브·마커, 구 모델의 도면 직결 마커 포함)를 detach delete 후 스냅샷으로
        재생성한다. `facility_id`가 있는 마커는 `LINKED_TO`로 Facility에 연결(merge_incident
        관례와 동일 stub 허용).

        `complex_name`이 있으면 단지 루트 `(:Complex {tenant_id})`를 실체화해
        `(fp)-[:PART_OF]->(complex)`로 잇는다(H13-7 — 도면에는 Location 개념이 없어
        직결만 한다, facility의 위치 경유 분기 없음).
        """
        devices = [dict(d) for d in props.get("devices") or []]
        # device_type이 빈 항목은 종류 허브를 만들 수 없어 제외한다(PG는 NOT NULL — 방어).
        # 남기면 허브 없는 고아 마커가 되어 다음 전체 교체의 순회에도 걸리지 않는다.
        markers = [
            d for d in devices if d.get("device_type") and d["device_type"] != _ROOM_DEVICE_TYPE
        ]
        await self._run(
            "MERGE (fp:FloorPlan {pg_id: $pg_id, tenant_id: $tenant}) "
            "ON CREATE SET fp.last_applied_version = -1 "
            "WITH fp WHERE $version > fp.last_applied_version "
            "SET fp.unit_type_name = $unit_type_name, fp.image_width = $image_width, "
            "    fp.image_height = $image_height, fp.last_applied_version = $version "
            "WITH fp "
            # 구 모델(도면 직결 마커)도 같은 패턴으로 걷힌다 — HAS_DEVICE를 함께 훑는다.
            "OPTIONAL MATCH (fp)-[:HAS_ROOM|HAS_KIND|HAS_DEVICE]->(old) "
            "OPTIONAL MATCH (old)-[:HAS_DEVICE]->(old_device:PlanDevice) "
            "DETACH DELETE old, old_device "
            "WITH DISTINCT fp "
            "FOREACH (_ IN CASE WHEN $complex_name IS NULL OR $complex_name = '' "
            "THEN [] ELSE [1] END | "
            "    MERGE (c:Complex {tenant_id: $tenant}) "
            "    SET c.name = $complex_name "
            "    MERGE (fp)-[:PART_OF]->(c)) "
            "WITH DISTINCT fp "
            "FOREACH (room IN $rooms | "
            "    CREATE (fp)-[:HAS_ROOM]->"
            "        (:PlanRoom {tenant_id: $tenant, plan_pg_id: $pg_id, name: room})) "
            "FOREACH (kind IN $kinds | "
            "    CREATE (fp)-[:HAS_KIND]->"
            "        (:PlanKind {tenant_id: $tenant, plan_pg_id: $pg_id, name: kind})) "
            "WITH fp "
            "UNWIND $devices AS device "
            "CREATE (d:PlanDevice {pg_id: device.pg_id, tenant_id: $tenant}) "
            "SET d.device_type = device.device_type, d.x = device.x, d.y = device.y, "
            "    d.room = device.room, d.dir = device.dir, d.label = device.label "
            "WITH fp, d, device "
            "MATCH (k:PlanKind {tenant_id: $tenant, plan_pg_id: $pg_id, name: device.device_type}) "
            "MERGE (k)-[:HAS_DEVICE]->(d) "
            "WITH d, device "
            "FOREACH (room IN CASE WHEN device.room IS NULL THEN [] ELSE [device.room] END | "
            "    MERGE (r:PlanRoom {tenant_id: $tenant, plan_pg_id: $pg_id, name: room}) "
            "    MERGE (r)-[:HAS_DEVICE]->(d)) "
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
                "devices": markers,
                "rooms": _plan_room_names(devices),
                "kinds": _distinct(d.get("device_type") for d in markers),
                "complex_name": props.get("complex_name"),
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

    async def fetch_facility_graph(self, *, tenant_id: str) -> FacilityGraph:
        """단지 시설 그래프 전체(노드 + 관계). 관계 0인 고아 시설도 노드로 포함.
        Location·Complex·FloorPlan 노드와 LOCATED_IN·PART_OF 관계는 항상 포함한다
        (H13-7·H14-1 — 기본 그래프의 뼈대, docs/11 §4 원 모델 + 단지 루트 노드).
        도면 하위 계층(PlanRoom·PlanKind·PlanDevice + HAS_ROOM·HAS_KIND·HAS_DEVICE·
        LINKED_TO)도 기본 포함 — 마커는 평면(도면 직결)이 아니라 방·종류 허브를 거쳐
        내려온다(H14-1 재구조화).

        tenant는 시설·이웃 양쪽에 강제한다. 반환 프로퍼티는 열거식 —
        `embedding`은 결과에 들어갈 수 없다(페이로드 폭발 방지, ADR-0022).
        """
        records = await self._run(
            "MATCH (f:Facility {tenant_id: $tenant}) "
            "OPTIONAL MATCH (f)-[r:HAS_INCIDENT|HAS_MAINTENANCE]->(n) "
            "WHERE n.tenant_id = $tenant "
            "RETURN f.pg_id AS facility_id, f.name AS facility_name, f.type AS facility_type, "
            "       f.code AS facility_code, "
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
                    code=r["facility_code"],
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

        await self._merge_location_graph(tenant_id=tenant_id, nodes=nodes, links=links)
        await self._merge_plan_graph(tenant_id=tenant_id, nodes=nodes, links=links)
        # 링크가 가리키는 노드가 먼저 존재해야 하므로(dangling 링크 방지) 도면 병합 뒤에 실행 —
        # FloorPlan發 PART_OF도 여기서 잡는다.
        await self._merge_complex_graph(tenant_id=tenant_id, nodes=nodes, links=links)

        return FacilityGraph(nodes=tuple(nodes.values()), links=tuple(links))

    async def _merge_location_graph(
        self, *, tenant_id: str, nodes: dict[str, GraphNode], links: list[GraphLink]
    ) -> None:
        """Location 노드·LOCATED_IN 관계를 fetch_facility_graph 결과에 덧붙인다 —
        기본 그래프의 뼈대라 항상 포함(H13-7)."""
        records = await self._run(
            "MATCH (f:Facility {tenant_id: $tenant})-[:LOCATED_IN]->"
            "(loc:Location {tenant_id: $tenant}) "
            "RETURN f.pg_id AS facility_id, loc.name AS location_name "
            "ORDER BY location_name",
            {"tenant": tenant_id},
        )
        for r in records:
            location_name = r["location_name"]
            if location_name not in nodes:
                nodes[location_name] = GraphNode(
                    pg_id=location_name, label="location", name=location_name
                )
            links.append(
                GraphLink(source=r["facility_id"], target=location_name, kind="LOCATED_IN")
            )

    async def _merge_complex_graph(
        self, *, tenant_id: str, nodes: dict[str, GraphNode], links: list[GraphLink]
    ) -> None:
        """단지 루트 Complex 노드·PART_OF 관계를 항상 덧붙인다(그래프 중심, H13-7 — 사용자
        요청). PART_OF 소스는 Facility(직결) 또는 Location(경유) — merge_facility가 위치
        유무로 이미 갈라 만든다. FloorPlan發 PART_OF(replace_floor_plan)도 포함 —
        도면은 기본 표시라 노드가 이미 결과에 실려있다(H14-1)."""
        records = await self._run(
            "MATCH (n)-[:PART_OF]->(c:Complex {tenant_id: $tenant}) "
            "WHERE n.tenant_id = $tenant AND (n:Facility OR n:Location OR n:FloorPlan) "
            "RETURN CASE WHEN n:Facility OR n:FloorPlan THEN n.pg_id ELSE n.name END AS source_id, "
            "       c.name AS complex_name "
            "ORDER BY complex_name",
            {"tenant": tenant_id},
        )
        for r in records:
            complex_name = r["complex_name"]
            if complex_name not in nodes:
                nodes[complex_name] = GraphNode(
                    pg_id=complex_name, label="complex", name=complex_name
                )
            links.append(GraphLink(source=r["source_id"], target=complex_name, kind="PART_OF"))

    async def _merge_plan_graph(
        self, *, tenant_id: str, nodes: dict[str, GraphNode], links: list[GraphLink]
    ) -> None:
        """평면도 계층(도면 → 방·종류 허브 → 마커)을 결과에 덧붙인다 — 기본 표시(H14-1).

        허브에는 pg_id가 없어(그래프 실체지만 PG 행이 아니다) `{도면}:room:{방}` /
        `{도면}:kind:{종류}` 형태의 합성 식별자를 쓴다(Location이 name을 pg_id로 쓰는 전례).
        마커는 방·종류 양쪽에서 내려와 행이 중복되므로 노드는 dict로 dedupe한다.
        """
        records = await self._run(
            "MATCH (fp:FloorPlan {tenant_id: $tenant}) "
            "OPTIONAL MATCH (fp)-[:HAS_ROOM|HAS_KIND]->(hub) "
            "OPTIONAL MATCH (hub)-[:HAS_DEVICE]->(d:PlanDevice) "
            "OPTIONAL MATCH (d)-[:LINKED_TO]->(f:Facility {tenant_id: $tenant}) "
            "RETURN fp.pg_id AS plan_id, fp.unit_type_name AS unit_type_name, "
            "       hub:PlanRoom AS is_room, hub.name AS hub_name, "
            "       d.pg_id AS device_id, d.device_type AS device_type, d.room AS room, "
            "       f.pg_id AS facility_id "
            "ORDER BY unit_type_name, hub_name, device_id",
            {"tenant": tenant_id},
        )
        linked_devices: set[str] = set()  # 마커는 방·종류 두 행에 나타난다 — LINKED_TO는 1회만
        for r in records:
            plan_id = r["plan_id"]
            if plan_id not in nodes:
                nodes[plan_id] = GraphNode(
                    pg_id=plan_id, label="floor_plan", name=r["unit_type_name"]
                )
            hub_name = r["hub_name"]
            if hub_name is None:  # 허브 0개인 도면
                continue
            is_room = bool(r["is_room"])
            hub_id = _plan_hub_id(plan_id, "room" if is_room else "kind", hub_name)
            if hub_id not in nodes:
                nodes[hub_id] = GraphNode(
                    pg_id=hub_id, label="plan_room" if is_room else "plan_kind", name=hub_name
                )
            links.append(
                GraphLink(source=plan_id, target=hub_id, kind="HAS_ROOM" if is_room else "HAS_KIND")
            )
            device_id = r["device_id"]
            if device_id is None:  # 마커 0개인 허브
                continue
            if device_id not in nodes:
                name = r["device_type"] if not r["room"] else f"{r['device_type']}({r['room']})"
                nodes[device_id] = GraphNode(pg_id=device_id, label="plan_device", name=name)
            links.append(GraphLink(source=hub_id, target=device_id, kind="HAS_DEVICE"))
            facility_id = r["facility_id"]
            if facility_id is not None and device_id not in linked_devices:
                linked_devices.add(device_id)
                links.append(GraphLink(source=device_id, target=facility_id, kind="LINKED_TO"))

    # ── 정리 (H14-1 — PG에서 사라진 도면의 잔존 노드) ───────────────────────

    async def prune_floor_plans(self, *, tenant_id: str, keep_pg_ids: Sequence[str]) -> int:
        """해당 tenant의 FloorPlan 중 `keep_pg_ids`에 없는 노드를 하위 계층(PlanRoom·PlanKind·
        PlanDevice)과 함께 삭제하고 삭제한 도면 수를 반환한다.

        PG 도면 행이 사라지면(과거 시드의 delete-then-insert 등) 그래프에는 tombstone
        이벤트가 없어 옛 노드가 고아로 남는다 — 시드가 현재 pg_id 집합으로 호출해 정리한다.
        `keep_pg_ids`가 비면 해당 tenant의 도면을 **전부** 지운다(PG에 도면 0건인 경우).
        tenant는 MATCH에 구조적으로 박혀 있어 타 tenant 노드는 대상이 될 수 없다.
        """
        records = await self._run(
            "MATCH (fp:FloorPlan {tenant_id: $tenant}) "
            "WHERE NOT fp.pg_id IN $keep "
            # HAS_DEVICE 직결은 구 모델(도면→마커) 잔재까지 함께 걷기 위한 것
            "OPTIONAL MATCH (fp)-[:HAS_ROOM|HAS_KIND|HAS_DEVICE]->(hub) "
            "OPTIONAL MATCH (hub)-[:HAS_DEVICE]->(d:PlanDevice) "
            "WITH collect(DISTINCT fp) AS plans, collect(DISTINCT hub) AS hubs, "
            "     collect(DISTINCT d) AS devices "
            "FOREACH (n IN plans + hubs + devices | DETACH DELETE n) "
            "RETURN size(plans) AS deleted",
            {"tenant": tenant_id, "keep": list(keep_pg_ids)},
        )
        return int(records[0]["deleted"]) if records else 0


def _plan_hub_id(plan_pg_id: str, hub: str, name: str) -> str:
    """방·종류 허브의 화면 식별자(pg_id 없는 노드 — Location이 name을 쓰는 전례)."""
    return f"{plan_pg_id}:{hub}:{name}"


def _distinct(values: Any) -> list[str]:
    """빈 값 제외 + 입력 순서 보존 중복 제거(그래프 허브 이름 목록)."""
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(str(value), None)
    return list(seen)


def _plan_room_names(devices: Sequence[Mapping[str, Any]]) -> list[str]:
    """방 허브 이름 — `device_type='room'` 항목의 방 이름 + 마커가 참조하는 방 이름.

    마커가 room 행 없는 방을 가리켜도 허브가 생겨 마커가 방 축에서 누락되지 않는다.
    """
    declared = (d.get("room") for d in devices if d.get("device_type") == _ROOM_DEVICE_TYPE)
    referenced = (d.get("room") for d in devices if d.get("device_type") != _ROOM_DEVICE_TYPE)
    return _distinct([*declared, *referenced])


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
