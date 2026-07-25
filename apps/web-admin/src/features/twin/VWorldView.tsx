"use client";

import { EmptyState } from "@liviq/ui";
import type { TwinGeometryItem } from "@/lib/api";
import {
  OVERLAY_LABELS,
  legendForOverlay,
  rgbCss,
  type OverlayKind,
  type RenderStyle,
} from "./twin-data";
import { useVWorld } from "./useVWorld";

// VWorld 프론트 키는 서비스 URL 도메인 잠금이라 번들 노출 무방(ADR-0019 개정, docs/06 §6).
// 미설정이면 실사 뷰만 안내로 대체하고 기본 deck.gl 뷰는 그대로 동작한다.
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY ?? "";

interface VWorldViewProps {
  geometry: TwinGeometryItem[];
  overlay: Record<string, number>; // household_id → 값(overlayKind 에 따라 의미가 다름)
  overlayKind: OverlayKind;
  renderStyle: RenderStyle; // 쉘·포인트·끄기(실사 3D 전용)
  cameraLock: boolean; // 시점 단지 고정
  orbit: boolean; // 360° 자동 회전
  clipOn: boolean; // 우리 단지만 표시
  onSelectHousehold: (householdId: string) => void;
}

/**
 * 실사 3D(VWorld/Cesium) 뷰 — 관리 셀 임베딩(ADR-0019 개정, H9-3b).
 * VWorld WebGL 위에 세대 shell Primitive 를 얹어 오버레이 색으로 상태를 겹쳐 본다.
 * 렌더는 iframe(vworld-iframe.ts) 안에서 수행하고, 부모는 세대별 색 계산·상태·범례를 담당한다
 * (VWorld 가 검증 후 document.write 로 주입하는 Cesium 엔진이 페이지 로드 후 동적 로드로는 안 뜨는
 * 실측 이슈 회피 — 문서 파싱 중인 iframe 이라 document.write 정상). 데이터·오버레이·세대 선택은
 * TwinDeck 과 동일 계약(props)으로 받는다 — 상세 패널은 TwinView 소유.
 */
export function VWorldView(props: VWorldViewProps) {
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
  return <VWorldCanvas apiKey={VWORLD_KEY} {...props} />;
}

interface VWorldCanvasProps extends VWorldViewProps {
  apiKey: string;
}

function VWorldCanvas({
  apiKey,
  geometry,
  overlay,
  overlayKind,
  renderStyle,
  cameraLock,
  orbit,
  clipOn,
  onSelectHousehold,
}: VWorldCanvasProps) {
  const { status, error, srcDoc, iframeRef, onLoad } = useVWorld({
    apiKey,
    geometry,
    overlay,
    overlayKind,
    renderStyle,
    cameraLock,
    orbit,
    clipOn,
    onSelectHousehold,
  });

  return (
    <div className="twin-canvas">
      {/* 실사 3D 는 iframe 안에서 렌더 — onLoad 에서 훅이 데이터를 postMessage 로 넘긴다. */}
      <iframe
        ref={iframeRef}
        className="twin-vworld-map"
        srcDoc={srcDoc}
        onLoad={onLoad}
        title="실사 3D 지도"
      />

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
