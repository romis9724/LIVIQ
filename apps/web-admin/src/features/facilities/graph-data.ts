/**
 * 시설 그래프 순수 로직 — 계통 그룹핑·색 매핑·클러스터 중심·검색·동명 매칭. (H13-1, ADR-0022)
 * 렌더·WebGL과 무관한 계산만 담는다(테스트 대상). three 렌더는 FacilityGraphCanvas.
 */

import type { GraphLink, GraphNode, GraphNodeLabel, Inquiry, InquiryStatus } from "@/lib/api";

/** type 이 없는 시설의 계통명. 그래프에 없는 값을 발명하지 않고 라벨만 붙인다. */
export const UNCLASSIFIED = "미분류";

// 색은 facilities.css :root 의 CSS 변수만 쓴다(하드코딩 금지). WebGL(three)은 oklch(color-4)를
// 못 읽어 그래프 전용 변수만 sRGB hex 로 정의돼 있다 — 범례 DOM 과 캔버스가 같은 변수를 읽는다.
export const SYSTEM_COLOR_VARS: readonly string[] = [
  "--fac-sys-1",
  "--fac-sys-2",
  "--fac-sys-3",
  "--fac-sys-4",
  "--fac-sys-5",
  "--fac-sys-6",
];
export const UNCLASSIFIED_COLOR_VAR = "--fac-sys-other";
export const INCIDENT_OPEN_COLOR_VAR = "--fac-node-incident-open";
export const INCIDENT_RESOLVED_COLOR_VAR = "--fac-node-incident-resolved";
export const MAINTENANCE_COLOR_VAR = "--fac-node-maintenance";
export const LINK_COLOR_VAR = "--fac-graph-link";
// H13-7 — 위치·평면도·단지 노드(계통/위치 렌즈와 무관한 고정색).
export const LOCATION_COLOR_VAR = "--fac-node-location";
export const FLOOR_PLAN_COLOR_VAR = "--fac-node-floor-plan";
export const COMPLEX_COLOR_VAR = "--fac-node-complex";
// H14-1 — 도면 하위 계층(방·종류 허브 → 마커). 평면도 계열 고정색.
export const PLAN_ROOM_COLOR_VAR = "--fac-node-plan-room";
export const PLAN_KIND_COLOR_VAR = "--fac-node-plan-kind";
export const PLAN_DEVICE_COLOR_VAR = "--fac-node-plan-device";

/** 노드 크기(nodeVal) — 시설이 이력보다 크게. 색만이 아니라 형태로도 유형이 구분되게.
 *  위치는 여러 설비가 모이는 허브라 시설보다 크게.
 *  단지는 tenant당 1개뿐인 최상위 허브라 가장 크다.
 *  방·종류 허브는 도면과 마커 사이라 중간, 마커는 도면당 수십개라 점처럼 작게(H14-1). */
export const NODE_VAL_FACILITY = 12;
export const NODE_VAL_EVENT = 3;
export const NODE_VAL_LOCATION = 20;
export const NODE_VAL_FLOOR_PLAN = 14;
export const NODE_VAL_PLAN_HUB = 7;
export const NODE_VAL_PLAN_DEVICE = 1.5;
export const NODE_VAL_COMPLEX = 30;
export const NODE_VAL_FOCUS_SCALE = 4;

/** 렌즈 그래프의 nodeVal 기준값 — 라벨별 크기(포커스 배율은 캔버스가 별도 적용). */
export function nodeBaseVal(label: GraphNodeLabel): number {
  switch (label) {
    case "facility":
      return NODE_VAL_FACILITY;
    case "location":
      return NODE_VAL_LOCATION;
    case "floor_plan":
      return NODE_VAL_FLOOR_PLAN;
    case "plan_room":
    case "plan_kind":
      return NODE_VAL_PLAN_HUB;
    case "plan_device":
      return NODE_VAL_PLAN_DEVICE;
    case "complex":
      return NODE_VAL_COMPLEX;
    default:
      return NODE_VAL_EVENT;
  }
}

/** 시설 노드의 계통명. type 이 없거나 공백이면 '미분류'. */
export function systemOf(node: GraphNode): string {
  const type = node.type?.trim();
  return type ? type : UNCLASSIFIED;
}

/** 계통 목록 — 시설 노드에서 추출(가나다 정렬, '미분류'는 항상 끝). 범례·색 배정의 기준. */
export function systemGroups(nodes: readonly GraphNode[]): string[] {
  const named = new Set<string>();
  let hasUnclassified = false;
  for (const node of nodes) {
    if (node.label !== "facility") continue;
    const system = systemOf(node);
    if (system === UNCLASSIFIED) hasUnclassified = true;
    else named.add(system);
  }
  const sorted = [...named].sort((a, b) => a.localeCompare(b, "ko"));
  return hasUnclassified ? [...sorted, UNCLASSIFIED] : sorted;
}

/** 계통(system) 렌즈에서 링크로 계통을 물려받을 수 있는 라벨 — 장애·정비뿐이다.
 *  location·floor_plan 은 여러 계통에 걸쳐 공유되는 노드라 계통 렌즈에서는
 *  중립으로 남긴다(클러스터 힘도 걸리지 않는다 — H13-7, ADR-0022 결정 2 확장). */
const SYSTEM_INHERITING_LABELS = new Set<GraphNodeLabel>(["incident", "maintenance"]);

/**
 * 노드 id → 계통. 장애·정비 노드는 링크의 source 시설 계통을 물려받는다
 * (그래프에 없는 가상 허브 노드를 만들지 않고 포스만으로 모으기 위한 기준 — ADR-0022 결정 2).
 */
export function systemByNodeId(
  nodes: readonly GraphNode[],
  links: readonly GraphLink[],
): Map<string, string> {
  const byId = new Map<string, string>();
  const labelById = new Map<string, GraphNodeLabel>();
  for (const node of nodes) {
    labelById.set(node.pgId, node.label);
    if (node.label === "facility") byId.set(node.pgId, systemOf(node));
  }
  for (const link of links) {
    const system = byId.get(link.source);
    if (!system || byId.has(link.target)) continue;
    if (SYSTEM_INHERITING_LABELS.has(labelById.get(link.target) as GraphNodeLabel)) {
      byId.set(link.target, system);
    }
  }
  return byId;
}

/** 계통 → 색 CSS 변수명. 팔레트를 넘는 계통은 순환한다(범례가 항상 매핑을 병기). */
export function systemColorVar(system: string, groups: readonly string[]): string {
  if (system === UNCLASSIFIED) return UNCLASSIFIED_COLOR_VAR;
  const index = groups.indexOf(system);
  if (index < 0) return UNCLASSIFIED_COLOR_VAR;
  return SYSTEM_COLOR_VARS[index % SYSTEM_COLOR_VARS.length]!;
}

/**
 * 노드 색 CSS 변수명 — 시설=계통색, 장애=미해결 경고색/해결 완화색, 정비=중립색.
 * 상태를 색만으로 전달하지 않는다(라벨·패널 텍스트 병기 — docs/05 §6).
 */
export function nodeColorVar(
  node: GraphNode,
  systemById: ReadonlyMap<string, string>,
  groups: readonly string[],
): string {
  return (
    eventColorVar(node) ?? systemColorVar(systemById.get(node.pgId) ?? systemOf(node), groups)
  );
}

// ── 렌즈(계통별/위치별) — H13-2, ADR-0022 결정 2 ────────────────────────────
// 계통 렌즈는 위 systemOf/systemGroups/systemByNodeId 그대로. 위치 렌즈는 buildingToken
// 기반 동 단위 그룹핑으로 같은 규칙(가나다 정렬·미상 그룹은 끝·이력 노드는 부모를 물려받음)을 따른다.

export type GraphLens = "system" | "location";

/** location 이 없거나 동 표기 추출 실패인 시설의 위치 그룹명. */
export const UNLOCATED = "미지정";

/** 시설 노드의 위치 그룹명(동 토큰). 동 표기가 없으면 '미지정'. */
export function locationOf(node: GraphNode): string {
  return buildingToken(node.location) ?? UNLOCATED;
}

/** 렌즈에 따른 노드 그룹명 — 계통(type) 또는 위치(동). */
export function groupOf(lens: GraphLens, node: GraphNode): string {
  return lens === "location" ? locationOf(node) : systemOf(node);
}

/** 렌즈별 그룹 목록(시설 노드 기준, 가나다 정렬, 미상 그룹은 항상 끝). 범례·색 배정의 기준. */
export function lensGroups(lens: GraphLens, nodes: readonly GraphNode[]): string[] {
  if (lens === "system") return systemGroups(nodes);
  const named = new Set<string>();
  let hasUnlocated = false;
  for (const node of nodes) {
    if (node.label !== "facility") continue;
    const group = locationOf(node);
    if (group === UNLOCATED) hasUnlocated = true;
    else named.add(group);
  }
  const sorted = [...named].sort((a, b) => a.localeCompare(b, "ko"));
  return hasUnlocated ? [...sorted, UNLOCATED] : sorted;
}

/** 위치(location) 렌즈에서 링크로 그룹을 물려받을 수 있는 라벨 — 장애·정비에 더해
 *  location 노드도 포함한다(위치 노드는 자기 그룹의 중심색을 그대로 쓴다 — H13-7 결정 3).
 *  floor_plan 과 그 하위 계층(plan_room·plan_kind·plan_device)은 고유색이 고정이라
 *  그룹 상속이 필요 없다. */
const LOCATION_INHERITING_LABELS = new Set<GraphNodeLabel>(["incident", "maintenance", "location"]);

/** 렌즈별 노드 id → 그룹(장애·정비는 링크 source 시설의 그룹을 물려받는다 — 결정 2). */
export function lensGroupByNodeId(
  lens: GraphLens,
  nodes: readonly GraphNode[],
  links: readonly GraphLink[],
): Map<string, string> {
  if (lens === "system") return systemByNodeId(nodes, links);
  const byId = new Map<string, string>();
  const labelById = new Map<string, GraphNodeLabel>();
  for (const node of nodes) {
    labelById.set(node.pgId, node.label);
    if (node.label === "facility") byId.set(node.pgId, locationOf(node));
  }
  for (const link of links) {
    const group = byId.get(link.source);
    if (!group || byId.has(link.target)) continue;
    if (LOCATION_INHERITING_LABELS.has(labelById.get(link.target) as GraphNodeLabel)) {
      byId.set(link.target, group);
    }
  }
  return byId;
}

/** 렌즈별 그룹 → 색 변수 — 같은 순환 팔레트 재사용, 위치 렌즈의 '미지정'은 중립색. */
export function lensColorVar(lens: GraphLens, group: string, groups: readonly string[]): string {
  if (lens === "location" && group === UNLOCATED) return UNCLASSIFIED_COLOR_VAR;
  return systemColorVar(group, groups);
}

/** 장애·정비·평면도(하위 계층 포함)·단지 노드의 고정색(계통/위치 렌즈 공통) — 그 외엔 null.
 *  location 은 렌즈에 따라 색이 달라져(결정 3) 여기서 다루지 않고 lensNodeColorVar 가 처리한다. */
function eventColorVar(node: GraphNode): string | null {
  if (node.label === "incident") {
    return node.resolved ? INCIDENT_RESOLVED_COLOR_VAR : INCIDENT_OPEN_COLOR_VAR;
  }
  if (node.label === "maintenance") return MAINTENANCE_COLOR_VAR;
  if (node.label === "floor_plan") return FLOOR_PLAN_COLOR_VAR;
  if (node.label === "plan_room") return PLAN_ROOM_COLOR_VAR;
  if (node.label === "plan_kind") return PLAN_KIND_COLOR_VAR;
  if (node.label === "plan_device") return PLAN_DEVICE_COLOR_VAR;
  if (node.label === "complex") return COMPLEX_COLOR_VAR;
  return null;
}

/**
 * 렌즈별 노드 색 변수. location 노드는 계통 렌즈에선 중립(여러 계통이 공유하는 노드라
 * 특정 계통색을 줄 수 없다), 위치 렌즈에선 자기 그룹(동)의 중심색을 그대로 쓴다(결정 3).
 */
export function lensNodeColorVar(
  lens: GraphLens,
  node: GraphNode,
  groupById: ReadonlyMap<string, string>,
  groups: readonly string[],
): string {
  const fixed = eventColorVar(node);
  if (fixed) return fixed;
  if (node.label === "location") {
    if (lens === "system") return LOCATION_COLOR_VAR;
    return lensColorVar(lens, groupById.get(node.pgId) ?? UNLOCATED, groups);
  }
  return lensColorVar(lens, groupById.get(node.pgId) ?? groupOf(lens, node), groups);
}

export interface Coords {
  x: number;
  y: number;
  z: number;
}

const CLUSTER_RADIUS = 160;

/** 계통 클러스터 중심 — XY 평면 원형 배치. 계통이 1개 이하면 원점(퍼뜨릴 이유가 없다). */
export function groupCenters(
  groups: readonly string[],
  radius: number = CLUSTER_RADIUS,
): Map<string, Coords> {
  const centers = new Map<string, Coords>();
  if (groups.length <= 1) {
    for (const group of groups) centers.set(group, { x: 0, y: 0, z: 0 });
    return centers;
  }
  groups.forEach((group, index) => {
    const angle = (2 * Math.PI * index) / groups.length;
    centers.set(group, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, z: 0 });
  });
  return centers;
}

/** 노드 id → 클러스터 중심(장애·정비는 부모 시설 계통을 따라간다). 포스 계산 입력. */
export function centerByNodeId(
  systemById: ReadonlyMap<string, string>,
  centers: ReadonlyMap<string, Coords>,
): Map<string, Coords> {
  const byId = new Map<string, Coords>();
  for (const [nodeId, system] of systemById) {
    const center = centers.get(system);
    if (center) byId.set(nodeId, center);
  }
  return byId;
}

const SEARCH_LIMIT = 20;

/** 검색 — 시설 노드 이름 부분일치(대소문자·공백 무시). 빈 질의는 빈 배열. */
export function searchFacilities(
  nodes: readonly GraphNode[],
  query: string,
  limit: number = SEARCH_LIMIT,
): GraphNode[] {
  const needle = normalize(query);
  if (!needle) return [];
  const hits: GraphNode[] = [];
  for (const node of nodes) {
    if (node.label !== "facility" || !node.name) continue;
    if (!normalize(node.name).includes(needle)) continue;
    hits.push(node);
    if (hits.length >= limit) break;
  }
  return hits;
}

/**
 * 이름 완전일치(검색창 입력·datalist 선택값 → 노드). 이름이 안 맞으면 코드번호 완전일치도
 * 본다(H14-2 — "EL-401-01" 로 바로 찾아가기). 그래도 없으면 이름 부분일치, 최종 실패는 null.
 */
export function findFacilityByName(nodes: readonly GraphNode[], name: string): GraphNode | null {
  const needle = normalize(name);
  if (!needle) return null;
  const exact = nodes.find(
    (node) => node.label === "facility" && node.name && normalize(node.name) === needle,
  );
  if (exact) return exact;
  const byCode = nodes.find(
    (node) => node.label === "facility" && node.code && normalize(node.code) === needle,
  );
  if (byCode) return byCode;
  return searchFacilities(nodes, name, 1)[0] ?? null;
}

/**
 * location 노드 클릭 → 이 위치에 LOCATED_IN 으로 연결된 시설 목록(그래프 데이터에서 파생,
 * 신규 API 없음 — H13-7 패널 요구사항). 링크 방향은 facility --LOCATED_IN--> location.
 */
export function facilitiesAtLocation(
  nodes: readonly GraphNode[],
  links: readonly GraphLink[],
  locationId: string,
): GraphNode[] {
  const facilityIds = new Set(
    links.filter((link) => link.kind === "LOCATED_IN" && link.target === locationId).map((link) => link.source),
  );
  return nodes.filter((node) => node.label === "facility" && facilityIds.has(node.pgId));
}

/**
 * 노드 클릭 → 상세를 열 시설 id. 시설은 자기 자신, 장애·정비 이력은 부모 시설(inbound 링크의
 * source — 이력 노드엔 상세 엔드포인트가 없다), 도면 마커는 배선된 설비(outbound `LINKED_TO`
 * 의 target — 그래프는 `plan_device --LINKED_TO--> facility` 방향으로 내려온다).
 * 방·종류 허브는 상세 대상이 아니고(상위가 도면이라 시설로 올라갈 수 없다), 미배선 마커도 null.
 */
export function facilityIdForNode(node: GraphNode, links: readonly GraphLink[]): string | null {
  if (node.label === "facility") return node.pgId;
  if (node.label === "plan_room" || node.label === "plan_kind") return null;
  if (node.label === "plan_device") {
    return (
      links.find((link) => link.kind === "LINKED_TO" && link.source === node.pgId)?.target ?? null
    );
  }
  return links.find((link) => link.target === node.pgId)?.source ?? null;
}

export interface ComplexSummary {
  locationCount: number;
  facilityCount: number;
  floorPlanCount: number;
  openIncidentCount: number;
}

/** 그래프 현황 요약(그래프 데이터 파생 — tenant당 complex 는 1개뿐이라 그래프의 노드 전체가
 *  곧 그 단지 집계다, H13-7). 플로팅 현황 패널과 complex 노드 패널이 같은 값을 쓴다(H14-1). */
export function complexSummary(nodes: readonly GraphNode[]): ComplexSummary {
  let locationCount = 0;
  let facilityCount = 0;
  let floorPlanCount = 0;
  let openIncidentCount = 0;
  for (const node of nodes) {
    if (node.label === "location") locationCount += 1;
    else if (node.label === "facility") facilityCount += 1;
    else if (node.label === "floor_plan") floorPlanCount += 1;
    else if (node.label === "incident" && !node.resolved) openIncidentCount += 1;
  }
  return { locationCount, facilityCount, floorPlanCount, openIncidentCount };
}

function normalize(value: string): string {
  return value.replace(/\s+/g, "").toLowerCase();
}

const BUILDING_PATTERN = /(\d+)\s*동/;

/** 위치 문자열에서 동 토큰 추출("401동 기계실" → "401동"). 동 표기가 없으면 null. */
export function buildingToken(location: string | null): string | null {
  if (!location) return null;
  const matched = BUILDING_PATTERN.exec(location);
  return matched ? `${matched[1]}동` : null;
}

/** 동 토큰이 텍스트에 나타나는지(공백 무시). 확정 연결이 아니라 추정 근거일 뿐이다. */
export function matchesBuilding(token: string, text: string): boolean {
  return normalize(text).includes(normalize(token));
}

const OPEN_STATUSES: readonly InquiryStatus[] = ["received", "assigned", "in_progress", "reopened"];

export interface EstimatedInquiries {
  token: string | null; // 추정 근거가 된 동 토큰(없으면 추정 자체를 하지 않는다)
  items: Inquiry[];
}

/**
 * 시설 위치의 동명이 제목·본문에 나타나는 **미종결** 민원(위치 추정 — ADR-0022 결정 3③).
 * 정식 연결(inquiries.facility_id)은 H13-2다. 화면은 반드시 '추정' 배지와 근거를 병기한다.
 */
export function estimatedInquiries(
  inquiries: readonly Inquiry[],
  location: string | null,
): EstimatedInquiries {
  const token = buildingToken(location);
  if (!token) return { token: null, items: [] };
  const items = inquiries.filter(
    (inquiry) =>
      OPEN_STATUSES.includes(inquiry.status) &&
      (matchesBuilding(token, inquiry.title) || matchesBuilding(token, inquiry.body)),
  );
  return { token, items };
}
