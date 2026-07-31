/**
 * 지하주차장 점유·배치도 순수 로직(H9-5 → H16-1 실데이터화).
 * 렌더·네트워크와 무관한 계산만 담는다(테스트 대상). SVG 렌더는 ParkingMap, 3D 는 parking-3d-data.
 *
 * 점유는 DB 정본(`parking_vehicles.spot_no`·`entry_at` — 현재는 시드 배정)이고 여기서는
 * 면 번호로 인덱싱만 한다. 입출차 카메라(번호판 인식) 연동 시 갱신 주체(시드 경로)만 교체하면
 * 되고 이 파일의 출력 계약은 그대로다: { bySpot: Map<spotNo, ParkedCar>, occupied: Set<spotNo> }.
 * (파일명 sim 은 H9-5 시뮬레이션 시절 잔재 — 참조가 많아 유지)
 */

import type { ParkingSpot, ParkingVehicle } from "@/lib/api";

// 배치도 축척 — 면 1개 34x64px = 2.5m x 5.0m (13px/m). 프로토타입과 동일해야 좌표가 맞는다.
export const SPOT_W = 34;
export const SPOT_H = 64;
export const PX_TO_M = 1 / 13;

/** 소속 필터의 "외부 차량" 그룹 키(동명이 아닌 유일 값). */
export const EXTERNAL_GROUP = "외부";

/** 배치도 위 사각 영역(코어·램프 등) — 거리 계산 기준. */
export interface ParkingRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

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

/**
 * 등록 차량 목록 → 면 점유. spotNo 가 있는 차량만 담는다(미주차 차량은 목록·지도에서 제외).
 * 한 면에 한 대는 DB 부분 유니크가 보장 — 그래도 중복이 오면 뒤 차량이 앞을 덮는다(마지막 승).
 * entryAt 이 없거나 파싱 불가면 entryMs 0 — 경과시간이 과대 표시되되 렌더는 깨지지 않는다.
 */
export function occupancyFromVehicles(vehicles: readonly ParkingVehicle[]): ParkingSim {
  const bySpot = new Map<string, ParkedCar>();
  for (const vehicle of vehicles) {
    if (!vehicle.spotNo) continue;
    const entryMs = vehicle.entryAt ? Date.parse(vehicle.entryAt) : Number.NaN;
    bySpot.set(vehicle.spotNo, {
      plate: vehicle.plate,
      dong: vehicle.dong,
      ho: vehicle.ho,
      model: vehicle.model,
      external: vehicle.external,
      entryMs: Number.isNaN(entryMs) ? 0 : entryMs,
    });
  }
  return { bySpot, occupied: new Set(bySpot.keys()) };
}

/** 면 중심 ↔ 사각 영역 중심 거리(px). */
export function dist(spot: ParkingSpot, rect: ParkingRect): number {
  return Math.hypot(
    spot.x + SPOT_W / 2 - (rect.x + rect.w / 2),
    spot.y + SPOT_H / 2 - (rect.y + rect.h / 2),
  );
}

/** 배치도 px → m(반올림). */
export function meters(px: number): number {
  return Math.round(px * PX_TO_M);
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
