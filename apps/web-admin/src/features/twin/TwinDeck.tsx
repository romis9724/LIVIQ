"use client";

import { useMemo, useState } from "react";
import { DeckGL, MapView, PolygonLayer } from "deck.gl";
import type { Color, MapViewState, PickingInfo } from "deck.gl";
import { EmptyState } from "@liviq/ui";
import type { TwinGeometryItem } from "@/lib/api";
import {
  OCCUPANCY_LEGEND,
  boundsToViewState,
  computeBounds,
  occupancyColor,
  rgbCss,
} from "./twin-data";

// 이 파일은 deck.gl(WebGL)만 다룬다 — TwinView 가 next/dynamic ssr:false 로만 로드한다.
const FILL_ALPHA = 220;
const LINE_COLOR: Color = [255, 255, 255, 90];
const INITIAL_PITCH = 50; // 3D 압출이 보이도록 기울임
const INITIAL_BEARING = 20;

interface TwinDeckProps {
  geometry: TwinGeometryItem[];
  overlay: Record<string, number>; // household_id → 세대원 수
}

/** WebGL 지원 여부 — 미지원이면 캔버스 대신 안내를 띄운다(클라이언트 전용). */
function webglSupported(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export function TwinDeck({ geometry, overlay }: TwinDeckProps) {
  const [failed, setFailed] = useState(false);
  const supported = useMemo(webglSupported, []);

  const initialViewState = useMemo<MapViewState>(() => {
    const bounds = computeBounds(geometry);
    const base = bounds ? boundsToViewState(bounds) : { longitude: 0, latitude: 0, zoom: 1 };
    return { ...base, pitch: INITIAL_PITCH, bearing: INITIAL_BEARING };
  }, [geometry]);

  const layer = useMemo(
    () =>
      new PolygonLayer<TwinGeometryItem>({
        id: "twin-units",
        data: geometry,
        extruded: true,
        wireframe: true,
        filled: true,
        pickable: true,
        // polygon3d 정점 z=base_z 라 층이 쌓이고, getElevation(층 높이)만큼 위로 압출된다.
        getPolygon: (d) => d.polygon3d,
        getElevation: (d) => d.floorHeight,
        getFillColor: (d): Color => {
          const [r, g, b] = occupancyColor(overlay[d.householdId] ?? 0);
          return [r, g, b, FILL_ALPHA];
        },
        getLineColor: LINE_COLOR,
        getLineWidth: 1,
        lineWidthUnits: "pixels",
        updateTriggers: { getFillColor: overlay },
      }),
    [geometry, overlay],
  );

  // H9-2 상세 패널 전까지는 hover tooltip(동·호·세대원 수)만 — 클릭 상세는 후속.
  const getTooltip = ({ object }: PickingInfo<TwinGeometryItem>) => {
    if (!object) return null;
    const count = overlay[object.householdId] ?? 0;
    return { text: `${object.buildingName} ${object.unitNo}호 · 세대원 ${count}명` };
  };

  if (!supported || failed) {
    return (
      <div className="twin-canvas twin-canvas--fallback">
        <EmptyState
          icon="🖥"
          title="3D 보기를 표시할 수 없습니다"
          description="이 브라우저·기기에서 WebGL을 사용할 수 없습니다. WebGL을 지원하는 최신 브라우저에서 다시 시도해 주세요."
        />
      </div>
    );
  }

  return (
    <div className="twin-canvas">
      <DeckGL
        views={new MapView({ repeat: false })}
        initialViewState={initialViewState}
        controller
        layers={[layer]}
        getTooltip={getTooltip}
        onError={() => setFailed(true)}
      />
      <ul className="twin-legend" aria-label="세대원 수 범례">
        {OCCUPANCY_LEGEND.map((entry) => (
          <li key={entry.label} className="twin-legend__item">
            <span
              className="twin-legend__swatch"
              style={{ backgroundColor: rgbCss(entry.color) }}
              aria-hidden="true"
            />
            {entry.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
