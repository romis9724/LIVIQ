"use client";

import { useMemo, useState } from "react";
import { DeckGL, MapView, PolygonLayer } from "deck.gl";
import type { Color, MapViewState, PickingInfo } from "deck.gl";
import { EmptyState } from "@liviq/ui";
import type { TwinGeometryItem } from "@/lib/api";
import {
  OVERLAY_LABELS,
  boundsToViewState,
  colorForOverlay,
  computeBounds,
  legendForOverlay,
  overlayValueText,
  rgbCss,
  type OverlayKind,
} from "./twin-data";

// 이 파일은 deck.gl(WebGL)만 다룬다 — TwinView 가 next/dynamic ssr:false 로만 로드한다.
const FILL_ALPHA = 220;
const LINE_COLOR: Color = [255, 255, 255, 90];
const INITIAL_PITCH = 50; // 3D 압출이 보이도록 기울임
const INITIAL_BEARING = 20;

interface TwinDeckProps {
  geometry: TwinGeometryItem[];
  overlay: Record<string, number>; // household_id → 값(overlayKind 에 따라 의미가 다름)
  overlayKind: OverlayKind;
  onSelectHousehold: (householdId: string) => void;
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

export function TwinDeck({ geometry, overlay, overlayKind, onSelectHousehold }: TwinDeckProps) {
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
          const [r, g, b] = colorForOverlay(overlayKind, overlay[d.householdId]);
          return [r, g, b, FILL_ALPHA];
        },
        getLineColor: LINE_COLOR,
        getLineWidth: 1,
        lineWidthUnits: "pixels",
        onClick: (info: PickingInfo<TwinGeometryItem>) => {
          if (info.object) onSelectHousehold(info.object.householdId);
          return true;
        },
        updateTriggers: { getFillColor: [overlayKind, overlay] },
      }),
    [geometry, overlay, overlayKind, onSelectHousehold],
  );

  // hover tooltip — 동·호 + 현재 오버레이 값(예 민원: "402 1202호 · 미종결 2건"). 클릭은 상세 패널.
  const getTooltip = ({ object }: PickingInfo<TwinGeometryItem>) => {
    if (!object) return null;
    const valueText = overlayValueText(overlayKind, overlay[object.householdId]);
    return { text: `${object.buildingName} ${object.unitNo}호 · ${valueText}` };
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
      <ul className="twin-legend" aria-label={`${OVERLAY_LABELS[overlayKind]} 범례`}>
        {legendForOverlay(overlayKind).map((entry) => (
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
