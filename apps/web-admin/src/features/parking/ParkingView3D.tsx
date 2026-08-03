"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  EmptyState,
  ParkingScene3D,
  SCENE_COLOR_VARS,
  isWebglSupported,
  sceneState,
  spotPlacements,
  type SceneColors,
  type SceneOccupant,
} from "@liviq/ui";
import type { ParkingLayout } from "@/lib/api";
import type { ParkedCar } from "./parking-sim";

// three(WebGL)를 쓰는 컴포넌트 — ParkingView 가 next/dynamic ssr:false 로만 불러온다.

const FALLBACK_COLOR = "#69737d"; // CSS 변수 조회 실패 시 중립 회색(정상 경로에선 쓰이지 않음)

interface ParkingView3DProps {
  layout: ParkingLayout;
  bySpot: ReadonlyMap<string, ParkedCar>;
  selectedNo: string | null;
  /** 강조할 소속("401동" | "외부") — 2D 지도와 같은 상태를 공유한다(미해당은 흐림). */
  activeGroup: string | null;
  /** AI 비서 딥링크(ADM-1) — 장기주차 면에 순번 비콘(주황, 오래된 순)을 세운다. */
  beaconNos?: readonly string[];
  onSelect: (spotNo: string) => void;
  /** 3D 뷰 요약(role=img aria-label) — 스크린리더 대안 경로는 2D 지도·목록 표다. */
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
 * 지하주차장 3D 뷰(H14-4) — 2D 배치도와 같은 데이터·같은 선택 상태를 입체로 보여 준다.
 * 씬 수명은 ParkingScene3D 가 소유하고, 여기서는 React 수명주기에 붙여 준다.
 */
export function ParkingView3D({
  layout,
  bySpot,
  selectedNo,
  activeGroup,
  beaconNos,
  onSelect,
  summaryLabel,
}: ParkingView3DProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<ParkingScene3D | null>(null);
  const onSelectRef = useRef(onSelect);
  const supported = useMemo(isWebglSupported, []);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const placements = useMemo(() => spotPlacements(layout.spots), [layout.spots]);
  // 공용 씬 계약(SceneOccupant)으로 접는다 — 그룹 키는 동명(2D 소속 필터와 동일).
  const occupants = useMemo(
    () =>
      new Map<string, SceneOccupant>(
        [...bySpot].map(([no, car]) => [no, { external: car.external, group: car.dong }]),
      ),
    [bySpot],
  );
  const state = useMemo(
    () => sceneState(placements, occupants, selectedNo, activeGroup),
    [placements, occupants, selectedNo, activeGroup],
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

  // 장기주차 비콘(ADM-1) — 외부 차량 색(주황)으로 오래된 순번을 세운다. 카메라 이동은
  // 딥링크가 첫 면을 선택 상태로 열어 아래 selectedNo 효과가 담당한다.
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    scene.setBeacons(
      (beaconNos ?? []).map((spotNo, index) => ({
        spotNo,
        label: String(index + 1),
        color: "external" as const,
      })),
    );
  }, [beaconNos, layout, supported]);

  // 면 선택(3D 클릭·목록 행·2D 지도 어디서 왔든) → 해당 면으로 카메라 이동.
  useEffect(() => {
    if (!selectedNo) return;
    sceneRef.current?.flyToSpot(selectedNo, prefersReducedMotion());
  }, [selectedNo]);

  // 탭이 숨으면 렌더 루프를 멈춘다(원본 setActive — GPU 절전).
  useEffect(() => {
    const handleVisibility = () => sceneRef.current?.setActive(!document.hidden);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  if (!supported) {
    return (
      <div className="pk-view3d__fallback">
        <EmptyState
          icon="🖥"
          title="3D 뷰를 표시할 수 없습니다"
          description="이 브라우저·기기에서 WebGL을 사용할 수 없습니다. ‘2D 배치도’ 보기와 목록에서 같은 주차 현황을 확인할 수 있습니다."
        />
      </div>
    );
  }

  return (
    <div className="pk-map">
      <div className="pk-zoom" role="group" aria-label="3D 카메라">
        {/* 클로즈업 뒤 "다른 데로 못 간다"는 신고 — 이동(팬)은 오른쪽 끌기라 안내에 적는다. */}
        <span className="pk-zoom__hint">끌어서 회전 · 휠로 확대 · 오른쪽 끌기로 이동</span>
        <button
          type="button"
          className="pk-zoom__reset"
          onClick={() => sceneRef.current?.flyOverview(prefersReducedMotion())}
        >
          전체 보기
        </button>
      </div>
      {/* 캔버스는 키보드로 다룰 수 없다 — 같은 정보를 2D 배치도와 목록 표가 대안으로 제공한다. */}
      <div className="pk-view3d" ref={containerRef} role="img" aria-label={summaryLabel} />
    </div>
  );
}
