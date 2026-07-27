/**
 * 시설 그래프 순수 로직 — 계통 그룹핑·색 매핑·클러스터 중심·검색·동명 매칭. (H13-1, ADR-0022)
 * 렌더·WebGL과 무관한 계산만 담는다(테스트 대상). three 렌더는 FacilityGraphCanvas.
 */

import type { GraphLink, GraphNode, Inquiry, InquiryStatus } from "@/lib/api";

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

/** 노드 크기(nodeVal) — 시설이 이력보다 크게. 색만이 아니라 형태로도 유형이 구분되게. */
export const NODE_VAL_FACILITY = 12;
export const NODE_VAL_EVENT = 3;
export const NODE_VAL_FOCUS_SCALE = 4;

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

/**
 * 노드 id → 계통. 장애·정비 노드는 링크의 source 시설 계통을 물려받는다
 * (그래프에 없는 가상 허브 노드를 만들지 않고 포스만으로 모으기 위한 기준 — ADR-0022 결정 2).
 */
export function systemByNodeId(
  nodes: readonly GraphNode[],
  links: readonly GraphLink[],
): Map<string, string> {
  const byId = new Map<string, string>();
  for (const node of nodes) {
    if (node.label === "facility") byId.set(node.pgId, systemOf(node));
  }
  for (const link of links) {
    const system = byId.get(link.source);
    if (system && !byId.has(link.target)) byId.set(link.target, system);
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
  if (node.label === "incident") {
    return node.resolved ? INCIDENT_RESOLVED_COLOR_VAR : INCIDENT_OPEN_COLOR_VAR;
  }
  if (node.label === "maintenance") return MAINTENANCE_COLOR_VAR;
  return systemColorVar(systemById.get(node.pgId) ?? systemOf(node), groups);
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

/** 이름 완전일치(검색창 입력·datalist 선택값 → 노드). 없으면 null. */
export function findFacilityByName(nodes: readonly GraphNode[], name: string): GraphNode | null {
  const needle = normalize(name);
  if (!needle) return null;
  const exact = nodes.find(
    (node) => node.label === "facility" && node.name && normalize(node.name) === needle,
  );
  if (exact) return exact;
  return searchFacilities(nodes, name, 1)[0] ?? null;
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
