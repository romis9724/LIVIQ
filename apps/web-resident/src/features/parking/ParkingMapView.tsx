"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Button,
  EmptyState,
  ParkingMap,
  Skeleton,
  elapsedText,
  type ParkingMapLayout,
  type ParkingSpotView,
} from "@liviq/ui";
import {
  ApiError,
  getParkingMap,
  type MyParkedVehicle,
  type ParkingCore,
  type ParkingMapData,
} from "./api";
import { readSpotParam } from "./links";
import { buildSpotDetail } from "./spot-detail";
import "./parking.css";

type DataState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: ParkingMapData };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

/** 입주민 주차맵 — 빈자리/점유 + 본인 차량 위치 + AI 비서 추천 면 강조(H17-2). */
export function ParkingMapView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [state, setState] = useState<DataState>({ kind: "loading" });
  // 경과시간 기준점 — 마운트 시 1회 고정(리렌더마다 흔들리지 않게).
  const [nowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", data: await getParkingMap() });
    } catch (err) {
      setState({ kind: "error", message: errorMessage(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const recommended = useMemo(() => readSpotParam(searchParams), [searchParams]);

  return (
    <div className="rpk">
      <header className="rpk__header">
        <button
          type="button"
          className="rpk__back"
          aria-label="뒤로가기"
          onClick={() => router.back()}
        >
          ←
        </button>
        <h1 id="main" className="rpk__title">
          주차장
        </h1>
      </header>

      <main className="rpk__main">
        {state.kind === "loading" ? (
          <Skeleton height="18rem" />
        ) : state.kind === "error" ? (
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
        ) : state.data.layout === null || state.data.layout.spots.length === 0 ? (
          <EmptyState
            icon="🅿️"
            title="주차장 배치도가 아직 준비되지 않았습니다"
            description="배치도가 등록되면 빈자리와 내 차 위치를 볼 수 있어요."
          />
        ) : (
          <ReadyView
            layout={state.data.layout}
            cores={state.data.cores}
            myDong={state.data.myDong}
            occupiedSpotNos={state.data.occupiedSpotNos}
            myVehicles={state.data.myVehicles}
            recommended={recommended}
            nowMs={nowMs}
          />
        )}
      </main>
    </div>
  );
}

interface ReadyViewProps {
  layout: ParkingMapLayout;
  cores: readonly ParkingCore[];
  myDong: string | null;
  occupiedSpotNos: readonly string[];
  myVehicles: readonly MyParkedVehicle[];
  recommended: readonly string[];
  nowMs: number;
}

function ReadyView({
  layout,
  cores,
  myDong,
  occupiedSpotNos,
  myVehicles,
  recommended,
  nowMs,
}: ReadyViewProps) {
  // 볼 면이 정해져 있으면(추천 자리 > 내 차) 선택 상태로 열어 지도가 그 면으로 포커스한다.
  const focusNo = recommended[0] ?? myVehicles[0]?.spotNo ?? null;
  const [selectedNo, setSelectedNo] = useState<string | null>(focusNo);

  const occupied = useMemo(() => new Set(occupiedSpotNos), [occupiedSpotNos]);
  const mineBySpot = useMemo(
    () => new Map(myVehicles.map((v) => [v.spotNo, v] as const)),
    [myVehicles],
  );

  const spotViews = useMemo(() => {
    const views = new Map<string, ParkingSpotView>();
    for (const spot of layout.spots) {
      const mine = mineBySpot.get(spot.no);
      const isOccupied = occupied.has(spot.no);
      views.set(spot.no, {
        // 타 세대 차량은 입주민/외부를 구분하지 않는다 — "찼다"만 보여준다(규칙 2).
        state: mine ? "mine" : isOccupied ? "occupied" : "empty",
        tooltip: spotTooltip(spot.no, spot.kind, isOccupied, mine, nowMs),
      });
    }
    return views;
  }, [layout.spots, occupied, mineBySpot, nowMs]);

  const emptyCount = layout.spots.filter((spot) => !occupied.has(spot.no)).length;
  const summary = `빈자리 ${emptyCount}면 / 전체 ${layout.spots.length}면`;

  return (
    <>
      {/* 색에 기대지 않도록 요약·내 차·선택 안내를 문구로 병기한다(WCAG 1.4.1). */}
      <p className="rpk__summary">{summary}</p>

      <MyCarNote vehicles={myVehicles} nowMs={nowMs} onFocus={setSelectedNo} />
      {recommended.length > 0 ? (
        <p className="rpk__recommend">
          <span aria-hidden="true">📍</span> AI 비서 추천 자리 {recommended.join("면 · ")}면 —
          지도에 보라색 점선으로 표시했어요.
        </p>
      ) : null}

      <section className="surface-card rpk__stage">
        <ParkingMap
          layout={layout}
          spotViews={spotViews}
          highlightNos={recommended}
          selectedNo={selectedNo}
          onSelect={setSelectedNo}
          summaryLabel={`지하 1층 주차 배치도 — ${summary}. 면을 누르면 상태를 읽어 줍니다.`}
          // 입주민 앱은 폭이 좁아 전체 보기로는 면이 안 보인다 — 볼 면이 있으면 확대해 연다.
          // 5×는 사용자 요청(2026-08-03) — 3×로는 면 번호가 작다.
          initialZoom={focusNo ? 5 : 1}
        />
        <MapLegend />
      </section>

      <SpotDetailPanel
        layout={layout}
        selectedNo={selectedNo}
        occupied={occupied}
        mineBySpot={mineBySpot}
        recommended={recommended}
        myDong={myDong}
        cores={cores}
        nowMs={nowMs}
      />

      <p className="rpk__note" role="note">
        다른 세대의 차량 정보는 표시하지 않습니다. 점유 현황은 데모 데이터입니다.
      </p>
    </>
  );
}

interface SpotDetailPanelProps {
  layout: ParkingMapLayout;
  selectedNo: string | null;
  occupied: ReadonlySet<string>;
  mineBySpot: ReadonlyMap<string, MyParkedVehicle>;
  recommended: readonly string[];
  myDong: string | null;
  cores: readonly ParkingCore[];
  nowMs: number;
}

/** 선택한 면의 상세 — 종류·상태·추천 순위·우리 동 승강기까지 거리(H20-5 상세화). */
function SpotDetailPanel({
  layout,
  selectedNo,
  occupied,
  mineBySpot,
  recommended,
  myDong,
  cores,
  nowMs,
}: SpotDetailPanelProps) {
  const spot = selectedNo ? layout.spots.find((s) => s.no === selectedNo) : undefined;
  if (!spot) {
    return (
      <p className="rpk__answer" role="status" aria-live="polite">
        배치도에서 주차면을 누르면 상세 정보가 표시됩니다.
      </p>
    );
  }
  const detail = buildSpotDetail({
    spot,
    isOccupied: occupied.has(spot.no),
    mine: mineBySpot.get(spot.no),
    recommendIndex: recommended.indexOf(spot.no),
    myDong,
    core: myDong ? cores.find((c) => c.name === myDong) : undefined,
    nowMs,
  });
  return (
    <div className="rpk__detail" role="status" aria-live="polite">
      <p className="rpk__detail-title">{detail.title}</p>
      {detail.lines.map((line) => (
        <p key={line} className="rpk__detail-line">
          {line}
        </p>
      ))}
    </div>
  );
}

interface MyCarNoteProps {
  vehicles: readonly MyParkedVehicle[];
  nowMs: number;
  onFocus: (spotNo: string) => void;
}

/** 본인 세대 차량 위치 — 누르면 지도가 그 면으로 포커스한다(키보드 대안 경로). */
function MyCarNote({ vehicles, nowMs, onFocus }: MyCarNoteProps) {
  if (vehicles.length === 0) {
    return (
      <p className="rpk__mycar" data-empty>
        <span aria-hidden="true">🚗</span> 주차 중인 우리 세대 차량이 없습니다.
      </p>
    );
  }
  return (
    <ul className="rpk__mycars" aria-label="우리 세대 차량 위치">
      {vehicles.map((vehicle) => (
        <li key={vehicle.spotNo}>
          <button type="button" className="rpk__mycar" onClick={() => onFocus(vehicle.spotNo)}>
            <span aria-hidden="true">🚗</span> 내 차: {vehicle.spotNo}면{entrySuffix(vehicle, nowMs)}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** " · 3시간 20분 전 입차" — 입차 시각이 없거나 깨졌으면 붙이지 않는다. */
function entrySuffix(vehicle: MyParkedVehicle, nowMs: number): string {
  if (!vehicle.entryAt) return "";
  const entryMs = Date.parse(vehicle.entryAt);
  if (Number.isNaN(entryMs)) return "";
  return ` · ${elapsedText(entryMs, nowMs)} 전 입차`;
}

/** 툴팁 — 색 단독 전달 금지라 면 상태를 문장으로 담는다. */
function spotTooltip(
  no: string,
  kind: string,
  isOccupied: boolean,
  mine: MyParkedVehicle | undefined,
  nowMs: number,
): string {
  const head = `${no}면${kind !== "일반" ? ` (${kind})` : ""}`;
  if (mine) return `${head} — 내 차${entrySuffix(mine, nowMs)}`;
  return `${head} — ${isOccupied ? "주차 중" : "빈자리"}`;
}

const LEGEND: readonly { state: string; label: string }[] = [
  { state: "empty", label: "빈자리" },
  { state: "occupied", label: "주차 중" },
  { state: "mine", label: "내 차" },
  { state: "recommend", label: "추천 자리" },
  { state: "accessible", label: "♿ 장애인 전용" },
  { state: "ev", label: "⚡ 전기차 충전" },
];

/** 범례 — 색+텍스트 병기(색 단독 전달 금지, docs/05 §6). */
function MapLegend() {
  return (
    <ul className="rpk-legend" aria-label="배치도 범례">
      {LEGEND.map((item) => (
        <li key={item.state} className="rpk-legend__item">
          <span className="rpk-legend__sw" data-state={item.state} aria-hidden="true" />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
