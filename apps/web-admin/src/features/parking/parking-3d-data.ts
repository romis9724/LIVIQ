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

/** 전체 부감 — 3D 진입 초기 시점(스윕 없이 즉시, 사용자 지시)이자 "전체 보기" 버튼 목적지. */
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

// ── 앰비언트 주행 차량(원본 cruiser 확장 — 5대) ────────────────────────────────
// 차로만 달린다: 주차열 띠(band) 사이의 통로 중앙을 가로 차선으로, 주차열 좌·우 바깥을
// 세로 연결로 삼아 사각 순환 경로를 만든다. 좌표는 배치도에서 파생 — 하드코딩 없음.

/** 순환 경로 1개 + 주행 파라미터(미터·m/s). */
export interface CruiseRoute {
  path: { x: number; z: number }[];
  speedMps: number;
  /** 출발 지점(경로 시작점부터의 거리) — 같은 경로의 차들이 뭉치지 않게 벌려 둔다. */
  startOffsetM: number;
}

/** 주행 차량 대수 — 바깥 순환 3대 + 안쪽 순환 2대. */
const OUTER_CRUISERS = 3;
const INNER_CRUISERS = 2;
const OUTER_SPEED_MPS = 6;
const INNER_SPEED_MPS = 4.4;
/** 안쪽 순환의 세로 연결선을 바깥과 겹치지 않게 들이는 양(통로 절반 기준 비율). */
const INNER_LANE_SHIFT = 0.45;

/** 같은 열에 붙은 주차면들을 하나의 띠로 묶는다(px) — 띠 사이 빈 곳이 통로다. */
function spotBands(spots: readonly ParkingSpot[]): { top: number; bottom: number }[] {
  const tops = [...new Set(spots.map((spot) => spot.y))].sort((a, b) => a - b);
  const bands: { top: number; bottom: number }[] = [];
  for (const top of tops) {
    const last = bands[bands.length - 1];
    if (last && top - last.bottom <= 0) {
      last.bottom = Math.max(last.bottom, top + SPOT_H);
      continue;
    }
    bands.push({ top, bottom: top + SPOT_H });
  }
  return bands;
}

/** 사각 순환 경로(미터) — 위·아래 가로 차선 + 좌·우 세로 연결. */
function loopPath(
  topPx: number,
  bottomPx: number,
  leftPx: number,
  rightPx: number,
): { x: number; z: number }[] {
  return [
    { x: toMeters(leftPx), z: toMeters(topPx) },
    { x: toMeters(rightPx), z: toMeters(topPx) },
    { x: toMeters(rightPx), z: toMeters(bottomPx) },
    { x: toMeters(leftPx), z: toMeters(bottomPx) },
  ];
}

/**
 * 주행 차량 5대의 경로 — 바깥 순환(주차열 위·아래 통로) 3대, 안쪽 순환(가운데 통로) 2대.
 * 두 순환은 세로 연결선 x 를 어긋나게 둬 교차 지점에서 겹치지 않는다.
 */
export function cruiseRoutes(spots: readonly ParkingSpot[]): CruiseRoute[] {
  const bands = spotBands(spots);
  if (bands.length < 2) return [];
  const first = bands[0];
  const last = bands[bands.length - 1];
  if (!first || !last) return [];

  // 통로 폭의 절반 — 바깥 차선·세로 연결선을 주차열에서 이만큼 띄운다.
  const aisleHalf = ((bands[1]?.top ?? first.bottom) - first.bottom) / 2;
  const left = Math.min(...spots.map((spot) => spot.x)) - aisleHalf;
  const right = Math.max(...spots.map((spot) => spot.x)) + SPOT_W + aisleHalf;
  const outer = loopPath(first.top - aisleHalf, last.bottom + aisleHalf, left, right);

  // 안쪽 순환은 첫 띠 아래·마지막 띠 위 통로를 쓴다(띠가 3개 미만이면 바깥과 같아지므로 생략).
  const shift = aisleHalf * INNER_LANE_SHIFT;
  const innerTop = first.bottom + aisleHalf;
  const innerBottom = last.top - aisleHalf;
  const hasInner = bands.length >= 3 && innerBottom > innerTop;
  const inner = hasInner
    ? loopPath(innerTop, innerBottom, left + shift, right - shift)
    : null;

  const routes: CruiseRoute[] = [];
  const outerCount = inner ? OUTER_CRUISERS : OUTER_CRUISERS + INNER_CRUISERS;
  const outerLength = pathLength(outer);
  for (let i = 0; i < outerCount; i += 1) {
    routes.push({
      path: outer,
      speedMps: OUTER_SPEED_MPS,
      startOffsetM: (outerLength * i) / outerCount,
    });
  }
  if (!inner) return routes;
  const innerLength = pathLength(inner);
  for (let i = 0; i < INNER_CRUISERS; i += 1) {
    routes.push({
      path: inner,
      speedMps: INNER_SPEED_MPS,
      startOffsetM: (innerLength * i) / INNER_CRUISERS,
    });
  }
  return routes;
}

/** 닫힌 경로의 총 길이(미터). */
export function pathLength(path: readonly { x: number; z: number }[]): number {
  let total = 0;
  for (let i = 0; i < path.length; i += 1) {
    const from = path[i];
    const to = path[(i + 1) % path.length];
    if (from && to) total += Math.hypot(to.x - from.x, to.z - from.z);
  }
  return total;
}

/** 경로 위 distance 지점의 좌표·진행 방향(rotY). 경로를 벗어난 거리는 순환으로 감싼다. */
export function pointAlongPath(
  path: readonly { x: number; z: number }[],
  distance: number,
): { x: number; z: number; rotY: number } {
  const total = pathLength(path);
  const start = path[0];
  if (!start || total === 0) return { x: start?.x ?? 0, z: start?.z ?? 0, rotY: 0 };
  let remain = ((distance % total) + total) % total;
  for (let i = 0; i < path.length; i += 1) {
    const from = path[i];
    const to = path[(i + 1) % path.length];
    if (!from || !to) break;
    const dx = to.x - from.x;
    const dz = to.z - from.z;
    const length = Math.hypot(dx, dz);
    if (length === 0) continue;
    if (remain <= length) {
      const t = remain / length;
      // 차 길이는 +z 축이라 atan2(dx, dz) 가 진행 방향을 향한 회전이다(주차 차량과 같은 규약).
      return { x: from.x + dx * t, z: from.z + dz * t, rotY: Math.atan2(dx, dz) };
    }
    remain -= length;
  }
  return { x: start.x, z: start.z, rotY: 0 };
}
