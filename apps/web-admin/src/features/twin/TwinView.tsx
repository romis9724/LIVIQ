"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { Button, EmptyState } from "@liviq/ui";
import {
  ApiError,
  getTwinOverlay,
  listTwinGeometry,
  type TwinGeometryItem,
} from "@/lib/api";
import {
  OVERLAY_KINDS,
  OVERLAY_LABELS,
  RENDER_STYLES,
  RENDER_STYLE_LABELS,
  type OverlayKind,
  type RenderStyle,
} from "./twin-data";
import { TabGroup } from "./TabGroup";
import { TwinDetailPanel } from "./TwinDetailPanel";
import { TwinStatusPanel } from "./TwinStatusPanel";
import "./twin.css";

// deck.gl 은 무겁다 — /twin 에서만 클라이언트로 로드해 타 페이지 번들에 새지 않게 한다(ADR-0019).
const TwinDeck = dynamic(() => import("./TwinDeck").then((m) => m.TwinDeck), {
  ssr: false,
  loading: () => (
    <div className="twin-canvas twin-canvas--loading" role="status" aria-live="polite">
      3D 모형 불러오는 중…
    </div>
  ),
});

// 실사 3D(VWorld/Cesium)도 dynamic 격리(deck.gl 과 동일 — 무거운 스택, ADR-0019 개정 H9-3).
const VWorldView = dynamic(() => import("./VWorldView").then((m) => m.VWorldView), {
  ssr: false,
  loading: () => (
    <div className="twin-canvas twin-canvas--loading" role="status" aria-live="polite">
      실사 3D 불러오는 중…
    </div>
  ),
});

// 렌더 엔진 선택 — 기본 3D(deck.gl) / 실사 3D(VWorld). 오버레이·세대 상세는 두 뷰 공통.
type ViewMode = "deck" | "vworld";
const VIEW_LABELS: Record<ViewMode, string> = { deck: "기본 3D", vworld: "실사 3D" };
const VIEW_MODES: readonly ViewMode[] = ["deck", "vworld"];

type GeoState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; geometry: TwinGeometryItem[] };

// 받아온 kind 는 캐시해 토글 시 재요청을 막는다(geometry 는 1회 로드).
type OverlayCache = Partial<Record<OverlayKind, Record<string, number>>>;

// 실사 3D 전용 컨트롤 상태(deck.gl 엔 대응 개념 없음 — 실사 3D 에서만 노출).
interface VWorldControls {
  renderStyle: RenderStyle;
  cameraLock: boolean;
  orbit: boolean;
  clipOn: boolean;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function TwinView() {
  const [geo, setGeo] = useState<GeoState>({ kind: "loading" });
  const [overlayKind, setOverlayKind] = useState<OverlayKind>("occupancy");
  const [overlays, setOverlays] = useState<OverlayCache>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("deck");

  const closeDetail = useCallback(() => setSelectedId(null), []);

  // 실사 3D 컨트롤 — 렌더 스타일·시점·clip. 뷰 전환에도 유지(iframe 재마운트 시 ready 효과가 재동기화).
  const [renderStyle, setRenderStyle] = useState<RenderStyle>("shell");
  // 단지 고정 기본 on — 인트로 후 iframe initialLock 이 재적용해 단지를 화면 중앙에 둔다.
  const [cameraLock, setCameraLock] = useState(true);
  const [orbit, setOrbit] = useState(false);
  const [clipOn, setClipOn] = useState(true);

  // 시점 토글 — 회전은 고정을 함의하고, 고정 해제는 회전도 끈다(iframe 동작과 일치).
  const toggleLock = () =>
    setCameraLock((on) => {
      if (on) setOrbit(false);
      return !on;
    });
  const toggleOrbit = () =>
    setOrbit((on) => {
      if (!on) setCameraLock(true);
      return !on;
    });

  const load = useCallback(async () => {
    setGeo({ kind: "loading" });
    setOverlays({});
    try {
      // geometry·초기 오버레이(입주)는 독립 — 병렬로 받아 왕복을 줄인다.
      const [geometry, occupancy] = await Promise.all([
        listTwinGeometry(),
        getTwinOverlay("occupancy"),
      ]);
      setGeo({ kind: "ready", geometry });
      setOverlays({ occupancy });
    } catch (err) {
      setGeo({ kind: "error", message: errorMessage(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 현재 kind 오버레이가 미캐시면 로드해 병합 — 캐시된 kind 는 재요청하지 않는다.
  useEffect(() => {
    if (geo.kind !== "ready" || overlays[overlayKind]) return;
    let alive = true;
    void getTwinOverlay(overlayKind)
      .then((values) => {
        if (alive) setOverlays((cur) => ({ ...cur, [overlayKind]: values }));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [overlayKind, geo.kind, overlays]);

  const showControls = geo.kind === "ready";
  const overlay = overlays[overlayKind] ?? {};
  const controls: VWorldControls = { renderStyle, cameraLock, orbit, clipOn };

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          트윈 대시보드
        </h1>
      </header>

      <main className="admin-page__main">
        {showControls ? (
          <div className="twin-controls">
            <TabGroup
              label="렌더 방식 선택"
              className="twin-views"
              tabClassName="twin-view-tab"
              options={VIEW_MODES}
              labels={VIEW_LABELS}
              active={viewMode}
              onSelect={setViewMode}
            />
            <TabGroup
              label="오버레이 선택"
              className="twin-overlays"
              tabClassName="twin-overlay-tab"
              options={OVERLAY_KINDS}
              labels={OVERLAY_LABELS}
              active={overlayKind}
              onSelect={setOverlayKind}
            />
            {viewMode === "vworld" ? (
              <div className="twin-vworld-controls">
                <TabGroup
                  label="렌더 스타일"
                  className="twin-styles"
                  tabClassName="twin-style-tab"
                  options={RENDER_STYLES}
                  labels={RENDER_STYLE_LABELS}
                  active={renderStyle}
                  onSelect={setRenderStyle}
                />
                <div className="twin-toggles" role="group" aria-label="시점·렌더링">
                  <ToggleButton pressed={cameraLock} onClick={toggleLock}>
                    단지 고정
                  </ToggleButton>
                  <ToggleButton pressed={orbit} onClick={toggleOrbit}>
                    360° 회전
                  </ToggleButton>
                  <ToggleButton pressed={clipOn} onClick={() => setClipOn((v) => !v)}>
                    우리 단지만
                  </ToggleButton>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
        <TwinBody
          geo={geo}
          occupancy={overlays.occupancy ?? {}}
          overlay={overlay}
          overlayKind={overlayKind}
          viewMode={viewMode}
          controls={controls}
          onRetry={() => void load()}
          onSelectHousehold={setSelectedId}
        />
      </main>

      {selectedId ? (
        <TwinDetailPanel householdId={selectedId} onClose={closeDetail} />
      ) : null}
    </>
  );
}

interface ToggleButtonProps {
  pressed: boolean;
  onClick: () => void;
  children: ReactNode;
}

/** 시점·렌더링 온오프 토글 — aria-pressed. */
function ToggleButton({ pressed, onClick, children }: ToggleButtonProps) {
  return (
    <button
      type="button"
      className="twin-toggle"
      aria-pressed={pressed}
      data-active={pressed || undefined}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

interface TwinBodyProps {
  geo: GeoState;
  occupancy: Record<string, number>;
  overlay: Record<string, number>;
  overlayKind: OverlayKind;
  viewMode: ViewMode;
  controls: VWorldControls;
  onRetry: () => void;
  onSelectHousehold: (householdId: string) => void;
}

function TwinBody({
  geo,
  occupancy,
  overlay,
  overlayKind,
  viewMode,
  controls,
  onRetry,
  onSelectHousehold,
}: TwinBodyProps) {
  if (geo.kind === "loading") {
    return (
      <section className="surface-card twin-stage">
        <div className="twin-canvas twin-canvas--loading" role="status" aria-live="polite">
          불러오는 중…
        </div>
      </section>
    );
  }

  if (geo.kind === "error") {
    return (
      <section className="surface-card twin-empty">
        <EmptyState
          icon="⚠"
          title="트윈 데이터를 불러오지 못했습니다"
          description={geo.message}
          action={
            <Button variant="secondary" onClick={onRetry}>
              다시 시도
            </Button>
          }
        />
      </section>
    );
  }

  if (geo.geometry.length === 0) {
    return (
      <section className="surface-card twin-empty">
        <EmptyState
          icon="🧊"
          title="등록된 세대 geometry가 없습니다"
          description="설정 > 동/호수 관리에서 units.json을 업로드하면 3D 트윈이 표시됩니다."
          action={
            <Link className="twin-empty__link" href="/settings/households">
              동/호수 관리로 이동
            </Link>
          }
        />
      </section>
    );
  }

  return (
    <div className="twin-layout">
      <TwinStatusPanel geometry={geo.geometry} occupancy={occupancy} />
      <section className="surface-card twin-stage">
        {viewMode === "vworld" ? (
          <VWorldView
            geometry={geo.geometry}
            overlay={overlay}
            overlayKind={overlayKind}
            renderStyle={controls.renderStyle}
            cameraLock={controls.cameraLock}
            orbit={controls.orbit}
            clipOn={controls.clipOn}
            onSelectHousehold={onSelectHousehold}
          />
        ) : (
          <TwinDeck
            geometry={geo.geometry}
            overlay={overlay}
            overlayKind={overlayKind}
            onSelectHousehold={onSelectHousehold}
          />
        )}
      </section>
    </div>
  );
}
