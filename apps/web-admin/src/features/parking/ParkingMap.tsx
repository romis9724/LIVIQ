"use client";

import { useMemo } from "react";
import { ParkingMap as UiParkingMap, type ParkingSpotView } from "@liviq/ui";
import type { ParkingLayout, ParkingSpot } from "@/lib/api";
import { elapsedText, matchesGroup, type ParkedCar } from "./parking-sim";

interface ParkingMapProps {
  layout: ParkingLayout;
  bySpot: ReadonlyMap<string, ParkedCar>;
  nowMs: number;
  /** 선택된 면 번호 — 강조 + 가로 스크롤 포커스. */
  selectedNo: string | null;
  /** 강조할 소속("401동" | "외부") — null 이면 전체 동일 강조. */
  activeGroup: string | null;
  onSelect: (spotNo: string) => void;
  /** 지도 요약(role=img aria-label) — 스크린리더는 목록 표를 대안 경로로 쓴다. */
  summaryLabel: string;
}

/**
 * 관리자 주차 배치도 어댑터 — 공용 `@liviq/ui` ParkingMap 에 관리자 표시 규칙만 얹는다(H17-2).
 * 소속 필터 dim 판정과 툴팁 문구(번호판·동호수 포함, 관리자 전용)는 앱 책임이다 —
 * ui 컴포넌트는 개인정보를 모르고 그리기만 한다(규칙 2).
 */
export function ParkingMap({
  layout,
  bySpot,
  nowMs,
  selectedNo,
  activeGroup,
  onSelect,
  summaryLabel,
}: ParkingMapProps) {
  const spotViews = useMemo(() => {
    const views = new Map<string, ParkingSpotView>();
    for (const spot of layout.spots) {
      const car = bySpot.get(spot.no);
      views.set(spot.no, {
        state: car ? (car.external ? "external" : "resident") : "empty",
        tooltip: spotTooltip(spot, car, nowMs),
        // 필터가 걸리면 해당 없는 면(빈자리 포함)을 흐리게 — 강조는 남은 면.
        dim: activeGroup !== null && !matchesGroup(car, activeGroup),
      });
    }
    return views;
  }, [layout.spots, bySpot, nowMs, activeGroup]);

  return (
    <UiParkingMap
      layout={layout}
      spotViews={spotViews}
      selectedNo={selectedNo}
      onSelect={onSelect}
      summaryLabel={summaryLabel}
    />
  );
}

/** 툴팁 — 면 번호·특수면 종류 + 차량 정보(관리자는 번호판 전체 표시). */
function spotTooltip(spot: ParkingSpot, car: ParkedCar | undefined, nowMs: number): string {
  const head = `${spot.no}면${spot.kind !== "일반" ? ` (${spot.kind})` : ""}`;
  if (!car) return `${head} — 빈자리`;
  if (car.external) {
    return `${head} — 외부차량 ${car.plate} · 주차 ${elapsedText(car.entryMs, nowMs)} 경과`;
  }
  return `${head} — ${car.plate} · ${car.dong} ${car.ho}`;
}
