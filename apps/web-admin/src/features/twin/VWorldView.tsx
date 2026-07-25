"use client";

import { EmptyState } from "@liviq/ui";
import type { TwinGeometryItem } from "@/lib/api";
import {
  OVERLAY_LABELS,
  legendForOverlay,
  rgbCss,
  type OverlayKind,
} from "./twin-data";
import { useVWorld } from "./useVWorld";

// VWorld 프론트 키는 서비스 URL 도메인 잠금이라 번들 노출 무방(ADR-0019 개정, docs/06 §6).
// 미설정이면 실사 뷰만 안내로 대체하고 기본 deck.gl 뷰는 그대로 동작한다.
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY ?? "";

interface VWorldViewProps {
  geometry: TwinGeometryItem[];
  overlay: Record<string, number>; // household_id → 값(overlayKind 에 따라 의미가 다름)
  overlayKind: OverlayKind;
  onSelectHousehold: (householdId: string) => void;
}

/**
 * 실사 3D(VWorld/Cesium) 뷰 — 관리 셀 임베딩(ADR-0019 개정, H9-3b).
 * VWorld WebGL 위에 세대 shell Primitive 를 얹어 오버레이 색으로 상태를 겹쳐 본다.
 * 데이터·오버레이·세대 선택은 TwinDeck 과 동일 계약(props)으로 받는다 — 상세 패널은 TwinView 소유.
 */
export function VWorldView({ geometry, overlay, overlayKind, onSelectHousehold }: VWorldViewProps) {
  if (!VWORLD_KEY) {
    return (
      <div className="twin-canvas twin-canvas--fallback">
        <EmptyState
          icon="🛰"
          title="VWorld 실사 3D 키가 설정되지 않았습니다"
          description="apps/web-admin/.env.local 에 NEXT_PUBLIC_VWORLD_API_KEY 를 설정하고 vworld.kr 에서 서비스 URL(http://localhost:3001)을 등록하면 실사 3D가 표시됩니다. 기본 3D 뷰는 그대로 사용할 수 있어요."
        />
      </div>
    );
  }

  // 키 확인 후에만 뷰어 훅을 태운다 — 훅 호출을 조건부로 두지 않도록 하위 컴포넌트로 분리.
  return (
    <VWorldCanvas
      apiKey={VWORLD_KEY}
      geometry={geometry}
      overlay={overlay}
      overlayKind={overlayKind}
      onSelectHousehold={onSelectHousehold}
    />
  );
}

interface VWorldCanvasProps extends VWorldViewProps {
  apiKey: string;
}

function VWorldCanvas({
  apiKey,
  geometry,
  overlay,
  overlayKind,
  onSelectHousehold,
}: VWorldCanvasProps) {
  const { status, error, containerId } = useVWorld({
    apiKey,
    geometry,
    overlay,
    overlayKind,
    onSelectHousehold,
  });

  return (
    <div className="twin-canvas">
      {/* 컨테이너는 항상 렌더 — 훅이 useEffect 에서 id 로 VWorld 맵을 붙인다. */}
      <div id={containerId} className="twin-vworld-map" />

      {status === "loading" ? (
        <div className="twin-vworld-status" role="status" aria-live="polite">
          실사 3D 불러오는 중…
        </div>
      ) : null}

      {status === "error" ? (
        <div className="twin-vworld-status">
          <EmptyState
            icon="🛰"
            title="실사 3D를 표시할 수 없습니다"
            description={`${error ?? "실사 3D 초기화에 실패했습니다."} 기본 3D 뷰는 정상 동작합니다.`}
          />
        </div>
      ) : null}

      {status === "ready" ? (
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
      ) : null}
    </div>
  );
}
