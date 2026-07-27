/**
 * 주차장 3D 뷰의 순수 변환 — 배치도 픽셀 좌표(13px/m)를 미터 바닥면(x,z)에 투영하고,
 * 점유 상태를 인스턴스 배열·카메라 샷으로 만든다. (H14-4)
 * 프로토타입 `parking_view3d.js` 의 좌표·상태 계산부 포팅.
 *
 * three 를 import 하지 않는다 — 렌더는 parking-scene-3d.ts 가 맡고 여기는 테스트 대상이다.
 */

import type { ParkingSpot } from "@/lib/api";
import { PX_TO_M, SPOT_H, SPOT_W, matchesGroup, parseViewBox, type ParkedCar } from "./parking-sim";

/** 면 상태 — 2D 지도와 같은 의미(빈자리·입주민·외부) + 3D 전용 두 가지(필터 흐림·선택). */
export type SpotTone = "empty" | "resident" | "external" | "dim" | "selected";
/** 차량은 빈자리 톤이 없다. */
export type CarTone = Exclude<SpotTone, "empty">;

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

/** 카메라 위치 + 바라보는 지점(미터). */
export interface CameraShot {
  position: Vec3;
  target: Vec3;
}

/** 면 1개의 바닥면 배치 — 배치도가 고정이라 마운트 때 1회 계산해 인스턴스 행렬로 굳힌다. */
export interface SpotPlacement {
  no: string;
  /** 면 중심(미터). */
  x: number;
  z: number;
  /** dir=down 이면 180° — 차량 앞뒤 방향. */
  rotY: number;
}

export interface CarInstance extends SpotPlacement {
  tone: CarTone;
}

/** 갱신마다 바뀌는 것 — 면 색(placements 와 같은 순서) + 차량 인스턴스. */
export interface SceneState {
  tones: SpotTone[];
  cars: CarInstance[];
}

/** 부감 스윕 종료 지점 — 바닥 폭 기준 비율. 가로로 긴 배치도가 무대를 채우도록 실측으로 잡았다
 *  (원본 값은 세로 여백이 크게 남았다 — 더 보려면 OrbitControls 로 물러나면 된다). */
const OVERVIEW_HEIGHT_RATIO = 0.36;
const OVERVIEW_BACK_RATIO = 0.17;
/** 진입 스윕 시작 지점 — 램프 쪽(좌하단) 저공. */
const ENTRY_HEIGHT_M = 2.5;
const ENTRY_SIDE_RATIO = 0.05;
/** 선택한 면 클로즈업 — 차 한 대가 화면을 채우지 않을 정도의 거리. */
const SPOT_FOCUS_HEIGHT_M = 16;
const SPOT_FOCUS_BACK_M = 22;
const SPOT_FOCUS_TARGET_Y_M = 1;

/** 배치도 픽셀 → 미터. */
export function toMeters(px: number): number {
  return px * PX_TO_M;
}

/** 바닥면 크기(미터) — viewBox 의 width·height. */
export function floorSize(viewBox: string): { w: number; h: number } {
  const [, , width, height] = parseViewBox(viewBox);
  return { w: toMeters(width), h: toMeters(height) };
}

/** 면 중심 좌표·회전(미터) — 순서는 입력 순서 그대로(인스턴스 index 계약). */
export function spotPlacements(spots: readonly ParkingSpot[]): SpotPlacement[] {
  return spots.map((spot) => ({
    no: spot.no,
    x: toMeters(spot.x + SPOT_W / 2),
    z: toMeters(spot.y + SPOT_H / 2),
    rotY: spot.dir === "down" ? Math.PI : 0,
  }));
}

/**
 * 면 색 + 주차 차량 인스턴스. 선택한 면이 최우선, 그다음 소속 필터 흐림(2D 지도의 data-dim 과
 * 같은 규칙 — 빈자리도 필터가 걸리면 흐려진다), 그다음 입주민/외부.
 */
export function sceneState(
  placements: readonly SpotPlacement[],
  bySpot: ReadonlyMap<string, ParkedCar>,
  selectedNo: string | null,
  activeGroup: string | null,
): SceneState {
  const tones: SpotTone[] = [];
  const cars: CarInstance[] = [];
  for (const placement of placements) {
    const car = bySpot.get(placement.no);
    const tone = spotTone(car, placement.no === selectedNo, activeGroup);
    tones.push(tone);
    // car 가 있으면 tone 은 empty 가 아니다 — 조건으로 좁혀 CarTone 으로 넘긴다.
    if (car && tone !== "empty") cars.push({ ...placement, tone });
  }
  return { tones, cars };
}

function spotTone(
  car: ParkedCar | undefined,
  selected: boolean,
  activeGroup: string | null,
): SpotTone {
  if (selected) return "selected";
  if (activeGroup !== null && !matchesGroup(car, activeGroup)) return "dim";
  if (!car) return "empty";
  return car.external ? "external" : "resident";
}

/** 진입 스윕 시작 — 램프 부근 저공에서 안쪽을 본다. */
export function entryShot(size: { w: number; h: number }): CameraShot {
  return {
    position: { x: size.w * ENTRY_SIDE_RATIO, y: ENTRY_HEIGHT_M, z: size.h - 4 },
    target: { x: size.w / 2, y: 0, z: size.h / 2 + 6 },
  };
}

/** 전체 부감 — 스윕 종료 지점이자 "전체 보기" 버튼 목적지. */
export function overviewShot(size: { w: number; h: number }): CameraShot {
  return {
    position: {
      x: size.w / 2,
      y: size.w * OVERVIEW_HEIGHT_RATIO,
      z: size.h + size.w * OVERVIEW_BACK_RATIO,
    },
    target: { x: size.w / 2, y: 0, z: size.h / 2 },
  };
}

/** 선택한 면 클로즈업 — 면 앞쪽 위에서 내려다본다. */
export function spotShot(placement: SpotPlacement): CameraShot {
  return {
    position: { x: placement.x, y: SPOT_FOCUS_HEIGHT_M, z: placement.z + SPOT_FOCUS_BACK_M },
    target: { x: placement.x, y: SPOT_FOCUS_TARGET_Y_M, z: placement.z },
  };
}

/** 동 footprint 폴리곤 → 미터 shape 좌표. y 는 부호가 뒤집힌다(배치도 y ↓ = 바닥 z ↑). */
export function outlineToShape(outline: readonly number[][]): { x: number; y: number }[] {
  return outline.map((point) => ({ x: toMeters(point[0] ?? 0), y: -toMeters(point[1] ?? 0) }));
}

/** 사각 구역(코어·램프 박스) 중심(미터). */
export function rectCenter(rect: { x: number; y: number; w: number; h: number }): {
  x: number;
  z: number;
} {
  return { x: toMeters(rect.x + rect.w / 2), z: toMeters(rect.y + rect.h / 2) };
}

/** 면 크기(미터) — 인스턴스 평면·주차선 지오메트리 공용. */
export const SPOT_W_M = toMeters(SPOT_W);
export const SPOT_H_M = toMeters(SPOT_H);
