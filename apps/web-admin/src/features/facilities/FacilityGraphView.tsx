"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import dynamic from "next/dynamic";
import { Button, EmptyState } from "@liviq/ui";
import {
  ApiError,
  getFacilityGraph,
  type FacilityGraph,
  type GraphNode,
  type GraphNodeLabel,
} from "@/lib/api";
import { FacilityGraphPanel, type GraphPanelSelection } from "./FacilityGraphPanel";
import {
  COMPLEX_COLOR_VAR,
  FLOOR_PLAN_COLOR_VAR,
  INCIDENT_OPEN_COLOR_VAR,
  INCIDENT_RESOLVED_COLOR_VAR,
  LOCATION_COLOR_VAR,
  MAINTENANCE_COLOR_VAR,
  PLAN_DEVICE_COLOR_VAR,
  PLAN_KIND_COLOR_VAR,
  PLAN_ROOM_COLOR_VAR,
  complexSummary,
  findFacilityByName,
  lensColorVar,
  lensGroups,
  type GraphLens,
} from "./graph-data";

// three.js 는 무겁다 — 시설 라우트에서만 클라이언트로 로드해 타 페이지 번들에 새지 않게 한다
// (ADR-0019 전례 · ADR-0022 결정 4 · docs/05 §7 번들 예산 예외 조건).
const FacilityGraphCanvas = dynamic(
  () => import("./FacilityGraphCanvas").then((m) => m.FacilityGraphCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="fac-graph__status" role="status" aria-live="polite">
        3D 그래프 불러오는 중…
      </div>
    ),
  },
);

const SEARCH_LIST_ID = "fac-graph-search-options";

const NODE_KIND_LEGEND: readonly { label: string; colorVar: string }[] = [
  { label: "장애(미해결)", colorVar: INCIDENT_OPEN_COLOR_VAR },
  { label: "장애(조치됨)", colorVar: INCIDENT_RESOLVED_COLOR_VAR },
  { label: "정비", colorVar: MAINTENANCE_COLOR_VAR },
];

// 위치·단지·평면도는 항상 표시(위치는 계통 렌즈에선 중립색, 위치 렌즈에선 위 그룹 목록의 색을
// 그대로 쓴다 — 이 스와치는 '위치 노드가 존재한다'는 표식일 뿐이다. 단지·평면도는 고정색).
const HUB_LEGEND: readonly { label: string; colorVar: string }[] = [
  { label: "위치(허브)", colorVar: LOCATION_COLOR_VAR },
  { label: "단지", colorVar: COMPLEX_COLOR_VAR },
];

// 도면 계층(H14-1) — 평면도 → 방·종류 허브 → 마커. 같은 주황 계열로 한 덩어리로 읽히게 한다.
const PLAN_LEGEND: readonly { label: string; colorVar: string }[] = [
  { label: "평면도", colorVar: FLOOR_PLAN_COLOR_VAR },
  { label: "방", colorVar: PLAN_ROOM_COLOR_VAR },
  { label: "종류", colorVar: PLAN_KIND_COLOR_VAR },
  { label: "마커(작은 점)", colorVar: PLAN_DEVICE_COLOR_VAR },
];

// 렌즈 — 계통별(기본)·위치별(동 단위, H13-2 ADR-0022 결정 2). 범례 제목도 렌즈에 따라 전환.
const LENS_OPTIONS: readonly { id: GraphLens; label: string }[] = [
  { id: "system", label: "계통별" },
  { id: "location", label: "위치별" },
];
const LENS_LEGEND_TITLE: Record<GraphLens, string> = {
  system: "계통(설비 노드)",
  location: "위치(설비 노드)",
};

// 상세 엔드포인트가 없는 도면 하위 노드 — 클릭해도 패널을 열지 않는다(H14-1).
const PLAN_SUBGRAPH_LABELS = new Set<GraphNodeLabel>(["plan_room", "plan_kind", "plan_device"]);

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; graph: FacilityGraph };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

interface FacilityGraphViewProps {
  onOpenList: () => void;
  onEditFloorPlan: (planId: string) => void;
}

/** 전체화면 3D 그래프 + 플로팅 패널 2개(왼쪽 현황·보기 설정 / 오른쪽 노드 상세) — H14-1. */
export function FacilityGraphView({ onOpenList, onEditFloorPlan }: FacilityGraphViewProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [lens, setLens] = useState<GraphLens>("system");
  const [selection, setSelection] = useState<GraphPanelSelection | null>(null);
  const [focus, setFocus] = useState<{ pgId: string; seq: number } | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  // 한글 IME 조합이 controlled input 에서 씹히므로 검색창은 uncontrolled(ref) 로 둔다.
  const searchRef = useRef<HTMLInputElement>(null);
  const focusSeq = useRef(0);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", graph: await getFacilityGraph() });
    } catch (err) {
      setState({ kind: "error", message: errorMessage(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const graph = state.kind === "ready" ? state.graph : null;
  const nodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const links = useMemo(() => graph?.links ?? [], [graph]);
  const groups = useMemo(() => lensGroups(lens, nodes), [lens, nodes]);
  const summary = useMemo(() => complexSummary(nodes), [nodes]);

  // 장애·정비 노드 클릭은 부모 시설의 패널을 연다(이력 노드 자체엔 상세 엔드포인트가 없다).
  const facilityIdOf = useCallback(
    (node: GraphNode): string | null => {
      if (node.label === "facility") return node.pgId;
      return links.find((link) => link.target === node.pgId)?.source ?? null;
    },
    [links],
  );

  // location·floor_plan·complex 는 전용 패널(H13-7). 도면 하위 계층(방·종류 허브·마커)은
  // 상세 엔드포인트가 없어 클릭을 조용히 무시한다(H14-1 — 잘못된 시설 패널을 여는 것보다 낫다).
  const handleSelectNode = useCallback(
    (node: GraphNode) => {
      if (PLAN_SUBGRAPH_LABELS.has(node.label)) return;
      if (node.label === "location") {
        setSelection({ kind: "location", node });
        return;
      }
      if (node.label === "floor_plan") {
        setSelection({ kind: "floor_plan", node });
        return;
      }
      if (node.label === "complex") {
        setSelection({ kind: "complex", node });
        return;
      }
      const facilityId = facilityIdOf(node);
      if (facilityId) setSelection({ kind: "facility", facilityId });
    },
    [facilityIdOf],
  );

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchRef.current?.value ?? "";
    const hit = findFacilityByName(nodes, query);
    if (!hit) {
      setSearchError(query.trim() ? "해당 이름·코드의 설비를 찾지 못했습니다." : null);
      return;
    }
    setSearchError(null);
    focusSeq.current += 1;
    setFocus({ pgId: hit.pgId, seq: focusSeq.current });
    setSelection({ kind: "facility", facilityId: hit.pgId });
  }

  // datalist 후보 — 이름과 코드번호 둘 다(코드로도 찾아갈 수 있다, H14-2).
  const searchOptions = [
    ...new Set(
      nodes
        .filter((node) => node.label === "facility")
        .flatMap((node) => [node.name, node.code].filter((v): v is string => Boolean(v))),
    ),
  ];

  return (
    <div className="fac-stage">
      <div className="fac-stage__canvas">
        {state.kind === "loading" ? (
          <div className="fac-graph__status" role="status" aria-live="polite">
            시설 그래프 불러오는 중…
          </div>
        ) : state.kind === "error" ? (
          <div className="fac-graph__empty">
            <EmptyState
              icon="⚠"
              title="시설 그래프를 불러오지 못했습니다"
              description={state.message}
              action={
                <Button variant="secondary" onClick={() => void load()}>
                  다시 시도
                </Button>
              }
            />
          </div>
        ) : nodes.length === 0 ? (
          <div className="fac-graph__empty">
            <EmptyState
              icon="🏗"
              title="시설이 없습니다"
              description="‘설비 목록·등록’에서 첫 시설을 추가하면 그래프에 나타납니다."
              action={
                <Button variant="secondary" onClick={onOpenList}>
                  설비 목록 열기
                </Button>
              }
            />
          </div>
        ) : (
          <section className="fac-stage__graph" aria-label="시설 관계 3D 그래프">
            <FacilityGraphCanvas
              nodes={nodes}
              links={links}
              groups={groups}
              lens={lens}
              focus={focus}
              onSelectNode={handleSelectNode}
            />
          </section>
        )}
      </div>

      <section className="fac-float fac-float--left" aria-label="시설 현황·보기 설정">
        <h2 className="fac-float__title">시설 현황</h2>
        <SummaryChips summary={summary} ready={state.kind === "ready"} />

        {graph?.degraded ? (
          <p className="fac-graph__banner" role="status">
            관계 정보 일시 미표시 — 설비 노드만 보여 줍니다. 장애·정비 연결은 그래프 동기화가
            복구되면 다시 나타납니다.
          </p>
        ) : null}

        <div className="fac-viewtabs" role="tablist" aria-label="그래프 렌즈">
          {LENS_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              role="tab"
              aria-selected={lens === option.id}
              className="fac-viewtab"
              data-active={lens === option.id || undefined}
              onClick={() => setLens(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <form className="fac-graph__search" role="search" onSubmit={handleSearch}>
          <label className="sr-only" htmlFor="fac-graph-search">
            설비 검색
          </label>
          <input
            id="fac-graph-search"
            ref={searchRef}
            className="fac-graph__search-input"
            type="search"
            list={SEARCH_LIST_ID}
            placeholder="설비 이름·코드 (예: 101동 승강기, EL-401-01)"
            autoComplete="off"
            onChange={() => setSearchError(null)}
          />
          <datalist id={SEARCH_LIST_ID}>
            {searchOptions.map((option) => (
              <option key={option} value={option} />
            ))}
          </datalist>
          <Button type="submit" variant="secondary">
            찾아가기
          </Button>
        </form>
        <p className="fac-graph__search-hint" role="status" aria-live="polite">
          {searchError ?? "노드를 클릭하면 오른쪽에 상세가 열립니다."}
        </p>

        <Legend lens={lens} groups={groups} />
      </section>

      {selection ? (
        <aside className="fac-float fac-float--right" aria-label="선택한 노드 상세">
          <div className="fac-float__bar">
            <button
              type="button"
              className="fac-float__close"
              onClick={() => setSelection(null)}
            >
              상세 닫기
            </button>
          </div>
          <FacilityGraphPanel
            selection={selection}
            nodes={nodes}
            links={links}
            onEditFloorPlan={onEditFloorPlan}
          />
        </aside>
      ) : null}
    </div>
  );
}

/** 현황 요약 — 설비·미해결 장애·위치·도면 수(그래프 데이터 파생, 신규 API 없음). */
function SummaryChips({
  summary,
  ready,
}: {
  summary: ReturnType<typeof complexSummary>;
  ready: boolean;
}) {
  const items: readonly { label: string; value: number; danger?: boolean }[] = [
    { label: "설비", value: summary.facilityCount },
    { label: "미해결 장애", value: summary.openIncidentCount, danger: true },
    { label: "위치", value: summary.locationCount },
    { label: "도면", value: summary.floorPlanCount },
  ];
  return (
    <ul className="fac-summary" aria-live="polite">
      {items.map((item) => (
        <li
          key={item.label}
          className="fac-summary__item"
          // 0건이면 경고색을 쓰지 않는다 — 문제 없음을 붉게 강조할 이유가 없다.
          data-tone={item.danger && item.value > 0 ? "danger" : undefined}
        >
          <span className="fac-summary__value">{ready ? item.value : "–"}</span>
          <span className="fac-summary__label">{item.label}</span>
        </li>
      ))}
    </ul>
  );
}

/** 범례 — 색만으로 상태를 전달하지 않도록 항상 라벨을 병기한다(docs/05 §6). 좁은 화면에서
 *  플로팅 패널이 커지지 않도록 접이식(details)으로 둔다. */
function Legend({ lens, groups }: { lens: GraphLens; groups: readonly string[] }) {
  return (
    <details className="fac-legend">
      <summary className="fac-legend__summary">범례</summary>
      <ul className="fac-legend__list">
        <li className="fac-graph__legend-title">{LENS_LEGEND_TITLE[lens]}</li>
        {groups.map((group) => (
          <li key={group} className="fac-graph__legend-item">
            <span
              className="fac-graph__legend-swatch fac-graph__legend-swatch--lg"
              style={{ backgroundColor: `var(${lensColorVar(lens, group, groups)})` }}
              aria-hidden="true"
            />
            {group}
          </li>
        ))}
        <li className="fac-graph__legend-title">이력 노드(작은 점)</li>
        {NODE_KIND_LEGEND.map((entry) => (
          <li key={entry.label} className="fac-graph__legend-item">
            <span
              className="fac-graph__legend-swatch"
              style={{ backgroundColor: `var(${entry.colorVar})` }}
              aria-hidden="true"
            />
            {entry.label}
          </li>
        ))}
        <li className="fac-graph__legend-title">허브 노드</li>
        {HUB_LEGEND.map((entry) => (
          <li key={entry.label} className="fac-graph__legend-item">
            <span
              className="fac-graph__legend-swatch fac-graph__legend-swatch--lg"
              style={{ backgroundColor: `var(${entry.colorVar})` }}
              aria-hidden="true"
            />
            {entry.label}
          </li>
        ))}
        <li className="fac-graph__legend-title">도면 계층(평면도 → 방·종류 → 마커)</li>
        {PLAN_LEGEND.map((entry) => (
          <li key={entry.label} className="fac-graph__legend-item">
            <span
              className="fac-graph__legend-swatch fac-graph__legend-swatch--lg"
              style={{ backgroundColor: `var(${entry.colorVar})` }}
              aria-hidden="true"
            />
            {entry.label}
          </li>
        ))}
      </ul>
    </details>
  );
}
