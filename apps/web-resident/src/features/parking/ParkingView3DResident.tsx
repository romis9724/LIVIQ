"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  EmptyState,
  ParkingScene3D,
  SCENE_COLOR_VARS,
  isWebglSupported,
  sceneState,
  spotPlacements,
  type ParkingSceneLayout,
  type SceneColors,
  type SceneOccupant,
} from "@liviq/ui";

// three(WebGL)를 쓰는 컴포넌트 — ParkingMapView 가 next/dynamic ssr:false 로만 불러온다.

const FALLBACK_COLOR = "#69737d"; // CSS 변수 조회 실패 시 중립 회색(정상 경로에선 쓰이지 않음)
/** 진입 직후 1순위 추천 자리로 카메라를 보내기까지의 지연 — 부감을 먼저 한 번 보여준다. */
const INTRO_FLY_DELAY_MS = 700;

interface ParkingView3DResidentProps {
  layout: ParkingSceneLayout;
  /** 점유 면 번호 — 입주민에겐 소속 구분이 없다("찼다"만, 규칙 2). */
  occupiedSpotNos: readonly string[];
  /** AI 추천 면(순서 = 순위) — 비콘 1·2·3 이 선다. */
  recommended: readonly string[];
  selectedNo: string | null;
  onSelect: (spotNo: string) => void;
  /** 3D 뷰 요약(role=img aria-label) — 스크린리더 대안 경로는 2D 배치도·상세 패널이다. */
  summaryLabel: string;
}

/** CSS 변수 → 색. three 는 oklch 를 못 읽어 3D 팔레트만 sRGB hex 로 따로 정의돼 있다. */
function resolveColors(): SceneColors {
  const style = getComputedStyle(document.documentElement);
  const entries = Object.entries(SCENE_COLOR_VARS).map(([key, name]) => [
    key,
    style.getPropertyValue(name).trim() || FALLBACK_COLOR,
  ]);
  return Object.fromEntries(entries) as SceneColors;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * 입주민 주차장 3D(H20-8) — 2D 배치도와 같은 데이터·같은 선택 상태를 입체로 보여 주고,
 * AI 추천 3자리에 순위 비콘(1·2·3)을 세운 뒤 1순위로 카메라를 보낸다(사용자 요구).
 */
export function ParkingView3DResident({
  layout,
  occupiedSpotNos,
  recommended,
  selectedNo,
  onSelect,
  summaryLabel,
}: ParkingView3DResidentProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<ParkingScene3D | null>(null);
  const onSelectRef = useRef(onSelect);
  const supported = useMemo(isWebglSupported, []);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const placements = useMemo(() => spotPlacements(layout.spots), [layout.spots]);
  // 타 세대 차량은 전부 익명 점유(소속 없음) — 씬 톤은 resident(파랑) 하나로 그려진다.
  const occupants = useMemo(
    () =>
      new Map<string, SceneOccupant>(
        occupiedSpotNos.map((no) => [no, { external: false, group: null }]),
      ),
    [occupiedSpotNos],
  );
  const state = useMemo(
    () => sceneState(placements, occupants, selectedNo, null),
    [placements, occupants, selectedNo],
  );

  // 씬 생성·해제 — 레이아웃이 바뀌면 통째로 다시 짓는다(면 위치가 인스턴스에 굳어 있다).
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !supported) return;
    const scene = new ParkingScene3D({
      container,
      layout,
      colors: resolveColors(),
      driving: !prefersReducedMotion(),
      onSpotClick: (spotNo) => onSelectRef.current(spotNo),
    });
    sceneRef.current = scene;
    scene.setActive(!document.hidden);
    return () => {
      sceneRef.current = null;
      scene.dispose();
    };
  }, [layout, supported]);

  useEffect(() => {
    sceneRef.current?.update(state);
  }, [state]);

  // 추천 비콘 + 진입 카메라 연출 — 부감을 잠깐 보여준 뒤 1순위 자리로 날아간다.
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    scene.setBeacons(recommended.map((spotNo, index) => ({ spotNo, rank: index + 1 })));
    const first = recommended[0];
    if (!first) return;
    if (prefersReducedMotion()) {
      scene.flyToSpot(first, true);
      return;
    }
    const timer = window.setTimeout(() => sceneRef.current?.flyToSpot(first, false), INTRO_FLY_DELAY_MS);
    return () => window.clearTimeout(timer);
    // layout 재생성 시 씬이 바뀌므로 함께 다시 건다.
  }, [recommended, layout, supported]);

  // 면 선택(3D 클릭·상세 패널 어디서 왔든) → 해당 면으로 카메라 이동.
  useEffect(() => {
    if (!selectedNo) return;
    sceneRef.current?.flyToSpot(selectedNo, prefersReducedMotion());
  }, [selectedNo]);

  // 탭이 숨으면 렌더 루프를 멈춘다(GPU 절전).
  useEffect(() => {
    const handleVisibility = () => sceneRef.current?.setActive(!document.hidden);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  if (!supported) {
    return (
      <EmptyState
        icon="🖥"
        title="3D 뷰를 표시할 수 없습니다"
        description="이 브라우저·기기에서 WebGL을 사용할 수 없습니다. 2D 배치도에서 같은 주차 현황을 확인할 수 있습니다."
      />
    );
  }

  return (
    <div className="rpk3d">
      <div className="rpk3d__bar">
        <span className="rpk3d__hint">끌어서 회전 · 휠·핀치로 확대</span>
        {recommended.map((spotNo, index) => (
          <button
            key={spotNo}
            type="button"
            className="rpk3d__chip"
            onClick={() => {
              onSelectRef.current(spotNo);
              sceneRef.current?.flyToSpot(spotNo, prefersReducedMotion());
            }}
          >
            {index + 1}순위 {spotNo}면
          </button>
        ))}
        <button
          type="button"
          className="rpk3d__chip rpk3d__chip--reset"
          onClick={() => sceneRef.current?.flyOverview(prefersReducedMotion())}
        >
          전체 보기
        </button>
      </div>
      {/* 캔버스는 키보드로 다룰 수 없다 — 같은 정보를 2D 배치도와 상세 패널이 대안으로 제공한다. */}
      <div className="rpk3d__stage" ref={containerRef} role="img" aria-label={summaryLabel} />
    </div>
  );
}
