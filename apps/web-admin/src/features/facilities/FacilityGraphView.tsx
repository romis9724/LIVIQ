"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import dynamic from "next/dynamic";
import { Button, EmptyState } from "@liviq/ui";
import { ApiError, getFacilityGraph, type FacilityGraph, type GraphNode } from "@/lib/api";
import { FacilityGraphPanel } from "./FacilityGraphPanel";
import {
  INCIDENT_OPEN_COLOR_VAR,
  INCIDENT_RESOLVED_COLOR_VAR,
  MAINTENANCE_COLOR_VAR,
  findFacilityByName,
  systemColorVar,
  systemGroups,
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

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; graph: FacilityGraph };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

interface FacilityGraphViewProps {
  onSwitchToList: () => void;
}

export function FacilityGraphView({ onSwitchToList }: FacilityGraphViewProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selectedFacilityId, setSelectedFacilityId] = useState<string | null>(null);
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
  const groups = useMemo(() => systemGroups(nodes), [nodes]);

  // 장애·정비 노드 클릭은 부모 시설의 패널을 연다(이력 노드 자체엔 상세 엔드포인트가 없다).
  const facilityIdOf = useCallback(
    (node: GraphNode): string | null => {
      if (node.label === "facility") return node.pgId;
      return links.find((link) => link.target === node.pgId)?.source ?? null;
    },
    [links],
  );

  const handleSelectNode = useCallback(
    (node: GraphNode) => {
      const facilityId = facilityIdOf(node);
      if (facilityId) setSelectedFacilityId(facilityId);
    },
    [facilityIdOf],
  );

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchRef.current?.value ?? "";
    const hit = findFacilityByName(nodes, query);
    if (!hit) {
      setSearchError(query.trim() ? "해당 이름의 설비를 찾지 못했습니다." : null);
      return;
    }
    setSearchError(null);
    focusSeq.current += 1;
    setFocus({ pgId: hit.pgId, seq: focusSeq.current });
    setSelectedFacilityId(hit.pgId);
  }

  const header = (
    <header className="admin-page__header">
      <h1 id="main" className="admin-page__title">
        시설 관리
      </h1>
      <p className="admin-page__lede">
        설비와 장애·정비 이력의 관계를 계통별로 봅니다. 확정 데이터만 표시하며, 상태 변경·기록은
        목록 보기에서 담당자가 직접 수행합니다.
      </p>
    </header>
  );

  if (state.kind === "loading") {
    return (
      <>
        {header}
        <div className="fac-graph__status" role="status" aria-live="polite">
          시설 그래프 불러오는 중…
        </div>
      </>
    );
  }

  if (state.kind === "error") {
    return (
      <>
        {header}
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
      </>
    );
  }

  if (nodes.length === 0) {
    return (
      <>
        {header}
        <div className="fac-graph__empty">
          <EmptyState
            icon="🏗"
            title="시설이 없습니다"
            description="목록 보기의 ‘설비 등록’으로 첫 시설을 추가하면 그래프에 나타납니다."
            action={
              <Button variant="secondary" onClick={onSwitchToList}>
                목록 보기로 전환
              </Button>
            }
          />
        </div>
      </>
    );
  }

  const facilityNames = nodes
    .filter((node) => node.label === "facility" && node.name)
    .map((node) => node.name as string);

  return (
    <>
      {header}
      <div className="fac-graph">
        {state.graph.degraded ? (
          <p className="fac-graph__banner" role="status">
            관계 정보 일시 미표시 — 설비 노드만 보여 줍니다. 장애·정비 연결은 그래프 동기화가
            복구되면 다시 나타납니다.
          </p>
        ) : null}

        <form className="fac-graph__search" role="search" onSubmit={handleSearch}>
          <label className="fac-graph__search-hint" htmlFor="fac-graph-search">
            설비 검색
          </label>
          <input
            id="fac-graph-search"
            ref={searchRef}
            className="fac-graph__search-input"
            type="search"
            list={SEARCH_LIST_ID}
            placeholder="설비 이름 (예: 101동 승강기)"
            autoComplete="off"
            onChange={() => setSearchError(null)}
          />
          <datalist id={SEARCH_LIST_ID}>
            {facilityNames.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
          <Button type="submit" variant="secondary">
            찾아가기
          </Button>
          <span className="fac-graph__search-hint" role="status" aria-live="polite">
            {searchError ?? "선택한 설비로 카메라가 이동합니다."}
          </span>
        </form>

        <div className="fac-graph__body">
          <section className="fac-graph__stage" aria-label="시설 관계 3D 그래프">
            <FacilityGraphCanvas
              nodes={nodes}
              links={links}
              groups={groups}
              focus={focus}
              onSelectNode={handleSelectNode}
            />
            <ul className="fac-graph__legend" aria-label="그래프 범례">
              <li className="fac-graph__legend-title">계통(설비 노드)</li>
              {groups.map((group) => (
                <li key={group} className="fac-graph__legend-item">
                  <span
                    className="fac-graph__legend-swatch fac-graph__legend-swatch--lg"
                    style={{ backgroundColor: `var(${systemColorVar(group, groups)})` }}
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
            </ul>
          </section>

          <FacilityGraphPanel facilityId={selectedFacilityId} />
        </div>
      </div>
    </>
  );
}
