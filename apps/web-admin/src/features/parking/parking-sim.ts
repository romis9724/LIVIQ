/**
 * 지하주차장 점유 — 순수 로직(H9-5 → H15-4 P1e).
 * 점유는 이제 서버 정본(parking_occupancy, ADR-0023)에서 읽는다 — 프론트 시뮬은 은퇴했다.
 * 이 모듈은 정본 응답을 렌더 계약(ParkedCar·ParkingSim)으로 옮기는 어댑터 + 집계·표시 헬퍼만
 * 담는다(테스트 대상). SVG 렌더는 ParkingMap, 3D 좌표는 parking-3d-data.
 */

import type { ParkingOccupancy, ParkingSpot } from "@/lib/api";

// 배치도 축척 — 면 1개 34x64px = 2.5m x 5.0m (13px/m). 프로토타입과 동일해야 좌표가 맞는다.
export const SPOT_W = 34;
export const SPOT_H = 64;
export const PX_TO_M = 1 / 13;

/** 소속 필터의 "외부 차량" 그룹 키(동명이 아닌 유일 값). */
export const EXTERNAL_GROUP = "외부";

/** 주차된 차량 1대. 입주민은 dong·ho·model 이 있고, 외부 차량은 번호판만 있다. */
export interface ParkedCar {
  plate: string;
  dong: string | null;
  ho: string | null;
  model: string | null;
  external: boolean;
  entryMs: number;
}

export interface ParkingSim {
  /** 면 번호 → 주차 차량. */
  bySpot: Map<string, ParkedCar>;
  occupied: Set<string>;
}

export interface ParkingCounts {
  total: number;
  occupied: number;
  resident: number;
  external: number;
  empty: number;
  /** 동명 → 주차 중인 입주민 차량 수(0인 동은 키가 없다). */
  byDong: Record<string, number>;
}

/** 배치도 px → m(반올림). */
export function meters(px: number): number {
  return Math.round(px * PX_TO_M);
}

/**
 * 점유 정본(parking_occupancy) → 렌더 계약(bySpot·occupied).
 * parked_hours 는 상대 경과라 nowMs 기준으로 입차시각을 역산한다 — 시간이 지나도 "N시간 전" 안정.
 * (nowMs 는 마운트 1회 고정 기준점.) 미상 경과(null)는 0시간(방금 입차)로 둔다.
 */
export function occupancyToSim(
  occupancy: readonly ParkingOccupancy[],
  nowMs: number,
): ParkingSim {
  const bySpot = new Map<string, ParkedCar>();
  for (const o of occupancy) {
    bySpot.set(o.spotNo, {
      plate: o.plate,
      dong: o.dong,
      ho: o.ho,
      model: o.model,
      external: o.isExternal,
      entryMs: nowMs - (o.parkedHours ?? 0) * 3600e3,
    });
  }
  return { bySpot, occupied: new Set(bySpot.keys()) };
}

/** 현황 카드·동별 칩 집계 — resident+external=occupied, occupied+empty=total. */
export function summarize(
  spots: readonly ParkingSpot[],
  bySpot: ReadonlyMap<string, ParkedCar>,
): ParkingCounts {
  const byDong: Record<string, number> = {};
  let external = 0;
  for (const car of bySpot.values()) {
    if (car.external) {
      external += 1;
      continue;
    }
    if (car.dong) byDong[car.dong] = (byDong[car.dong] ?? 0) + 1;
  }
  const occupied = bySpot.size;
  return {
    total: spots.length,
    occupied,
    resident: occupied - external,
    external,
    empty: spots.length - occupied,
    byDong,
  };
}

/** 소속 필터 대조 — "외부"는 외부 차량, 그 외는 동명. 빈자리는 어느 그룹에도 속하지 않는다. */
export function matchesGroup(car: ParkedCar | undefined, group: string): boolean {
  if (!car) return false;
  return group === EXTERNAL_GROUP ? car.external : car.dong === group;
}

/** "0 0 3020 1082" → [minX, minY, width, height]. 파싱 실패는 0 으로 둔다(2D·3D 공용). */
export function parseViewBox(viewBox: string): [number, number, number, number] {
  const parts = viewBox
    .trim()
    .split(/[\s,]+/)
    .map((v) => Number.parseFloat(v));
  return [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0, parts[3] ?? 0];
}

/** 주차 경과 시간 — "3시간 20분" / "20분". 미래 입차(음수)는 "0분". */
export function elapsedText(entryMs: number, nowMs: number): string {
  const minutes = Math.max(0, Math.floor((nowMs - entryMs) / 60000));
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours > 0 ? `${hours}시간 ${rest}분` : `${rest}분`;
}
