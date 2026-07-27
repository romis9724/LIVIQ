"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { Button, EmptyState, Skeleton } from "@liviq/ui";
import {
  ApiError,
  getParkingLayout,
  listParkingVehicles,
  type ParkingLayout,
  type ParkingSpot,
  type ParkingVehicle,
} from "@/lib/api";
import {
  EXTERNAL_GROUP,
  SIM_SEED,
  simulateParking,
  summarize,
  elapsedText,
  type ParkedCar,
  type ParkingCounts,
} from "./parking-sim";
import { ParkingMap } from "./ParkingMap";
import { ParkingList } from "./ParkingList";
import "./parking.css";

// three.js 는 무겁다 — 3D 뷰는 옵트인이라 눌렀을 때만 클라이언트로 불러온다
// (기본 2D 배치도는 그대로, 타 라우트·초기 진입 번들에 three 가 새지 않게 — ADR-0022 결정 4).
const ParkingView3D = dynamic(() => import("./ParkingView3D").then((m) => m.ParkingView3D), {
  ssr: false,
  loading: () => (
    <div className="pk-view3d__status" role="status" aria-live="polite">
      3D 뷰 불러오는 중…
    </div>
  ),
});

type ViewMode = "2d" | "3d";

const VIEW_MODES: readonly { id: ViewMode; label: string }[] = [
  { id: "2d", label: "2D 배치도" },
  { id: "3d", label: "3D 뷰" },
];

type CountKey = Exclude<keyof ParkingCounts, "byDong">;

interface SummaryTile {
  key: CountKey;
  label: string;
  unit: string;
  /** 카드 강조 톤 — 지도 색 체계와 같은 의미(입주민 파랑·외부 주황·빈자리 초록). */
  tone?: "resident" | "external" | "empty";
}

const SUMMARY_TILES: readonly SummaryTile[] = [
  { key: "total", label: "전체 면", unit: "면" },
  { key: "occupied", label: "주차", unit: "대" },
  { key: "resident", label: "입주민", unit: "대", tone: "resident" },
  { key: "external", label: "외부", unit: "대", tone: "external" },
  { key: "empty", label: "빈자리", unit: "면", tone: "empty" },
];

type DataState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; layout: ParkingLayout | null; vehicles: ParkingVehicle[] };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function ParkingView() {
  const [state, setState] = useState<DataState>({ kind: "loading" });
  // 입차시각 기준점 — 마운트 시 1회 고정(시뮬레이션·경과시간이 리렌더마다 흔들리지 않게).
  const [nowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      // 레이아웃·차량은 독립 — 병렬로 받아 왕복을 줄인다(트윈 로드와 동일 패턴).
      const [layout, vehicles] = await Promise.all([getParkingLayout(), listParkingVehicles()]);
      setState({ kind: "ready", layout, vehicles });
    } catch (err) {
      setState({ kind: "error", message: errorMessage(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          주차장 대시보드
        </h1>
        <p className="admin-page__lede">
          지하 1층 배치도에서 입주민·외부 차량을 확인합니다. 면을 누르면 어느 동 몇 호 차량인지
          표시됩니다.
        </p>
        <p className="pk-sim-badge">
          <span aria-hidden="true">🧪</span> 점유 현황은 시뮬레이션입니다(번호판 인식 연동 전).
          배치도·차량 목록은 등록 데이터입니다.
        </p>
      </header>

      <main className="admin-page__main">
        {state.kind === "loading" ? (
          <LoadingSkeleton />
        ) : state.kind === "error" ? (
          <section className="surface-card pk-empty">
            <EmptyState
              icon="⚠"
              title="주차장 현황을 불러오지 못했습니다"
              description={state.message}
              action={
                <Button variant="secondary" onClick={() => void load()}>
                  다시 시도
                </Button>
              }
            />
          </section>
        ) : state.layout === null || state.layout.spots.length === 0 ? (
          <section className="surface-card pk-empty">
            <EmptyState
              icon="🅿️"
              title="주차장 배치도가 없습니다 — 시드 필요"
              description="지하주차장 레이아웃(면·동 footprint)이 등록되면 배치도가 표시됩니다."
            />
          </section>
        ) : (
          <ReadyView layout={state.layout} vehicles={state.vehicles} nowMs={nowMs} />
        )}
      </main>
    </>
  );
}

function LoadingSkeleton() {
  return (
    <div className="pk-stack">
      <Skeleton height="88px" />
      <Skeleton height="420px" />
    </div>
  );
}

interface ReadyViewProps {
  layout: ParkingLayout;
  vehicles: readonly ParkingVehicle[];
  nowMs: number;
}

function ReadyView({ layout, vehicles, nowMs }: ReadyViewProps) {
  const [selectedNo, setSelectedNo] = useState<string | null>(null);
  const [group, setGroup] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(false);
  // 기본은 2D — 3D 는 옵트인이고, WebGL 이 없거나 느린 기기는 2D 로 계속 볼 수 있다.
  const [viewMode, setViewMode] = useState<ViewMode>("2d");

  // 점유는 마운트 1회 계산 — 시드·nowMs 고정이라 재렌더에도 같은 상태를 보여준다.
  const sim = useMemo(
    () => simulateParking(layout.spots, layout.cores, vehicles, SIM_SEED, nowMs),
    [layout, vehicles, nowMs],
  );
  const counts = useMemo(() => summarize(layout.spots, sim.bySpot), [layout.spots, sim]);
  const dongs = useMemo(() => layout.buildings.map((b) => b.name), [layout.buildings]);
  const selectedSpot = selectedNo
    ? layout.spots.find((spot) => spot.no === selectedNo) ?? null
    : null;

  return (
    <div className="pk-stack">
      <ul className="pk-summary" aria-label="주차 현황 요약">
        {SUMMARY_TILES.map((tile) => (
          <li key={tile.key} className="pk-tile" data-tone={tile.tone}>
            <span className="pk-tile__label">{tile.label}</span>
            <span className="pk-tile__value">
              {counts[tile.key].toLocaleString()}
              <span className="pk-tile__unit">{tile.unit}</span>
            </span>
          </li>
        ))}
      </ul>

      <div className="pk-groups" role="group" aria-label="소속별 주차 대수">
        {dongs.map((dong) => (
          <GroupChip
            key={dong}
            label={`${dong} ${counts.byDong[dong] ?? 0}대`}
            active={group === dong}
            onClick={() => setGroup(group === dong ? null : dong)}
          />
        ))}
        <GroupChip
          label={`외부 ${counts.external}대`}
          tone="external"
          active={group === EXTERNAL_GROUP}
          onClick={() => setGroup(group === EXTERNAL_GROUP ? null : EXTERNAL_GROUP)}
        />
        <div className="pk-viewtabs" role="group" aria-label="배치도 보기 방식">
          {VIEW_MODES.map((mode) => (
            <button
              key={mode.id}
              type="button"
              className="pk-viewtab"
              aria-pressed={viewMode === mode.id}
              data-active={viewMode === mode.id || undefined}
              onClick={() => setViewMode(mode.id)}
            >
              {mode.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="pk-list-toggle"
          aria-pressed={listOpen}
          data-active={listOpen || undefined}
          onClick={() => setListOpen((open) => !open)}
        >
          목록 보기
        </button>
      </div>

      <p className="pk-answer" role="status" aria-live="polite">
        {selectionText(selectedSpot, selectedNo ? sim.bySpot.get(selectedNo) : undefined, nowMs)}
      </p>

      <div className="pk-main" data-list={listOpen || undefined}>
        <section className="surface-card pk-stage">
          {viewMode === "3d" ? (
            <ParkingView3D
              layout={layout}
              bySpot={sim.bySpot}
              selectedNo={selectedNo}
              activeGroup={group}
              onSelect={setSelectedNo}
              summaryLabel={mapSummaryLabel(counts)}
            />
          ) : (
            <ParkingMap
              layout={layout}
              bySpot={sim.bySpot}
              nowMs={nowMs}
              selectedNo={selectedNo}
              activeGroup={group}
              onSelect={setSelectedNo}
              summaryLabel={mapSummaryLabel(counts)}
            />
          )}
          <MapLegend />
        </section>

        {listOpen ? (
          <ParkingList
            bySpot={sim.bySpot}
            group={group}
            dongs={dongs}
            nowMs={nowMs}
            selectedNo={selectedNo}
            onGroupChange={setGroup}
            onSelect={setSelectedNo}
          />
        ) : null}
      </div>

      <p className="pk-note" role="note">
        <span aria-hidden="true">🔒</span> 차량번호는 개인정보입니다. 관리 목적으로만 사용하세요.
      </p>
    </div>
  );
}

interface GroupChipProps {
  label: string;
  active: boolean;
  tone?: "external";
  onClick: () => void;
}

function GroupChip({ label, active, tone, onClick }: GroupChipProps) {
  return (
    <button
      type="button"
      className="pk-chip"
      data-tone={tone}
      data-active={active || undefined}
      aria-pressed={active}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

const LEGEND: readonly { state: string; label: string }[] = [
  { state: "empty", label: "빈자리" },
  { state: "resident", label: "입주민 차량" },
  { state: "external", label: "외부 차량" },
  { state: "accessible", label: "♿ 장애인 전용" },
  { state: "ev", label: "⚡ 전기차 충전" },
  { state: "selected", label: "선택한 면" },
];

/** 범례 — 색+텍스트 병기(색 단독 전달 금지, docs/05 §6). */
function MapLegend() {
  return (
    <ul className="pk-legend" aria-label="배치도 범례">
      {LEGEND.map((item) => (
        <li key={item.state} className="pk-legend__item">
          <span className="pk-legend__sw" data-state={item.state} aria-hidden="true" />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/** 지도 요약 — role=img aria-label(스크린리더는 목록 표에서 면 단위를 읽는다). */
function mapSummaryLabel(counts: ParkingCounts): string {
  return `지하 1층 주차 배치도 — 전체 ${counts.total}면 중 주차 ${counts.occupied}면(입주민 ${counts.resident}·외부 ${counts.external}), 빈자리 ${counts.empty}면. 면별 상세는 목록 보기 표에서 확인하세요.`;
}

/** 선택한 면 안내(프로토타입 answer 영역) — 빈자리·입주민·외부 3가지. */
function selectionText(
  spot: ParkingSpot | null,
  car: ParkedCar | undefined,
  nowMs: number,
): string {
  if (!spot) return "배치도에서 주차면을 누르면 차량 정보가 표시됩니다.";
  const kindSuffix = spot.kind !== "일반" ? ` (${spot.kind} 전용)` : "";
  if (!car) return `${spot.no}면${kindSuffix} — 빈자리`;
  if (car.external) {
    return `${spot.no}면 — 🚨 외부 차량 ${car.plate} · 등록 차량 아님 · 주차 ${elapsedText(car.entryMs, nowMs)} 경과`;
  }
  const model = car.model ? `${car.model}(${car.plate})` : car.plate;
  return `${spot.no}면 — ${car.dong} ${car.ho} 차량 · ${model} · 주차 ${elapsedText(car.entryMs, nowMs)} 경과`;
}
