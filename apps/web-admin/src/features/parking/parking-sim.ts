/**
 * 지하주차장 점유 시뮬레이션 — 순수 로직(H9-5).
 * AI_digitaltwin_apartment 프로토타입 `parking_layout.js` 의 simulateParking 포팅.
 * 렌더·네트워크와 무관한 계산만 담는다(테스트 대상). SVG 렌더는 ParkingMap.
 *
 * ★ 실서비스 교체 지점: 입출차 카메라(번호판 인식) API 로 교체.
 *   출력 계약: { bySpot: Map<spotNo, ParkedCar>, occupied: Set<spotNo> }
 *   external = 번호판이 입주민 차량 목록에 없는 차량.
 */

import type { ParkingCore, ParkingSpot, ParkingVehicle } from "@/lib/api";

// 배치도 축척 — 면 1개 34x64px = 2.5m x 5.0m (13px/m). 프로토타입과 동일해야 좌표가 맞는다.
export const SPOT_W = 34;
export const SPOT_H = 64;
export const PX_TO_M = 1 / 13;

/** 시드·재실률 — 두 화면이 같은 점유 상태를 보도록 고정(프로토타입 동일 값). */
export const SIM_SEED = 20260725;
export const OCCUPANCY_RATE = 0.75;

const EXTERNAL_COUNT = 8;
const HOUR_MS = 3600e3;
/** 근처 선호 스코어에 섞는 무작위 편차(px) — 자기 동 주변이 먼저 차되 딱 붙지는 않게. */
const PICK_JITTER_PX = 500;
/** 외부 차량 번호판 생성 재시도 상한 — 중복이 계속되면 그 대수는 건너뛴다(무한 루프 방지). */
const PLATE_ATTEMPTS = 50;
const PLATE_LETTERS = "가나다라마거너더러머버서어저허";

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

/** mulberry32 — 시드 고정 결정적 PRNG(프로토타입과 동일 구현). */
export function makeRand(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
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

/**
 * 입구(진입 램프) 근사 — 배치도 좌하단.
 * ponytail: 램프 박스를 인자로 받지 않고 면 좌표에서 유도한다(스코어는 상대값 + 편차라 충분).
 *           램프 위치가 좌하단이 아닌 레이아웃이 생기면 boxes 를 인자로 넘겨 교체.
 */
function entranceOf(spots: readonly ParkingSpot[]): ParkingRect | null {
  if (spots.length === 0) return null;
  let minX = Infinity;
  let maxY = -Infinity;
  for (const sp of spots) {
    if (sp.x < minX) minX = sp.x;
    if (sp.y > maxY) maxY = sp.y;
  }
  return { x: minX, y: maxY + SPOT_H, w: 160, h: 64 };
}

/**
 * 점유 시뮬레이션. 입주민 차량은 재실률 rate 만큼 주차하고 자기 동 코어 근처를 선호한다.
 * 장애인면은 배정하지 않고, 전기차 충전면은 EV 만 배정한다. 외부 차량 8대는 입구 근처 선호.
 * nowMs 는 입차시각 기준점 — Date.now() 를 직접 읽지 않아 결과가 결정적이다.
 */
export function simulateParking(
  spots: readonly ParkingSpot[],
  cores: readonly ParkingCore[],
  vehicles: readonly ParkingVehicle[],
  seed: number,
  nowMs: number,
  rate: number = OCCUPANCY_RATE,
): ParkingSim {
  const rand = makeRand(seed);
  const bySpot = new Map<string, ParkedCar>();
  const taken = new Set<string>();
  const coreByDong = new Map(cores.map((c) => [c.name, c] as const));
  const knownPlates = new Set(vehicles.map((v) => v.plate));

  // near(코어·입구) 근처 선호 + 무작위 편차. 최저 스코어 면을 고른다(동점이면 앞선 면).
  const pick = (isEv: boolean, near: ParkingRect | null): ParkingSpot | null => {
    let best: ParkingSpot | null = null;
    let bestScore = Infinity;
    for (const sp of spots) {
      if (taken.has(sp.no) || sp.kind === "장애인") continue;
      if (sp.kind === "전기차" && !isEv) continue;
      const score = (near ? dist(sp, near) : sp.x) + rand() * PICK_JITTER_PX;
      if (score < bestScore) {
        bestScore = score;
        best = sp;
      }
    }
    return best;
  };

  for (const vehicle of vehicles) {
    if (rand() >= rate) continue;
    const spot = pick(vehicle.isEv, coreByDong.get(vehicle.dong) ?? null);
    if (!spot) break;
    taken.add(spot.no);
    const hours = 0.5 + rand() * 13.5;
    bySpot.set(spot.no, {
      plate: vehicle.plate,
      dong: vehicle.dong,
      ho: vehicle.ho,
      model: vehicle.model,
      external: false,
      entryMs: nowMs - hours * HOUR_MS,
    });
  }

  const entrance = entranceOf(spots);
  for (let i = 0; i < EXTERNAL_COUNT; i += 1) {
    const plate = nextExternalPlate(rand, knownPlates);
    if (!plate) continue;
    const spot = pick(false, entrance);
    if (!spot) break;
    taken.add(spot.no);
    knownPlates.add(plate);
    // 절반은 장기 주차(20~72시간) — 방치 차량 식별 시나리오.
    const hours = i % 2 === 0 ? 1 + rand() * 8 : 20 + rand() * 52;
    bySpot.set(spot.no, {
      plate,
      dong: null,
      ho: null,
      model: null,
      external: true,
      entryMs: nowMs - hours * HOUR_MS,
    });
  }

  return { bySpot, occupied: new Set(bySpot.keys()) };
}

/** 입주민 차량과 겹치지 않는 임의 번호판. 상한까지 중복이면 null. */
function nextExternalPlate(rand: () => number, used: ReadonlySet<string>): string | null {
  for (let attempt = 0; attempt < PLATE_ATTEMPTS; attempt += 1) {
    const head = 100 + Math.floor(rand() * 900);
    const letter = PLATE_LETTERS.charAt(Math.floor(rand() * PLATE_LETTERS.length));
    const tail = 1000 + Math.floor(rand() * 9000);
    const plate = `${head}${letter}${tail}`;
    if (!used.has(plate)) return plate;
  }
  return null;
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
