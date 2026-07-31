import { describe, expect, it } from "vitest";

import type { TwinGeometryItem } from "@/lib/api";
import {
  ZOOM_MAX_RANGE_M,
  ZOOM_MIN_RANGE_M,
  ZOOM_STEP,
  centerOf,
  nextOrbitRange,
  scaleCoords,
} from "./vworld-render";

function item(polygon2d: number[][]): TwinGeometryItem {
  return {
    householdId: "h",
    buildingName: "101동",
    floor: 1,
    unitNo: 101,
    polygon2d,
    polygon3d: polygon2d.map((v) => [v[0] ?? 0, v[1] ?? 0, 0]),
    baseZ: 0,
    floorHeight: 3,
    areaM2: null,
    unitTypeLabel: null,
  };
}

describe("centerOf", () => {
  it("첫 정점 평균으로 단지 중심을 낸다", () => {
    const center = centerOf([
      item([[127.0, 37.0]]),
      item([[127.2, 37.4]]),
    ]);
    expect(center).toEqual([127.1, 37.2]);
  });

  it("정점이 없으면 원점", () => {
    expect(centerOf([])).toEqual([0, 0]);
    expect(centerOf([item([])])).toEqual([0, 0]);
  });
});

describe("scaleCoords", () => {
  it("무게중심 기준으로 폴리곤을 확장한다", () => {
    // 중심 (0,0) 정사각형을 2배 확장 → 각 정점이 원점에서 2배 멀어진다.
    const scaled = scaleCoords(
      [
        [-1, -1],
        [1, -1],
        [1, 1],
        [-1, 1],
      ],
      2,
    );
    expect(scaled).toEqual([
      [-2, -2],
      [2, -2],
      [2, 2],
      [-2, 2],
    ]);
  });

  it("f=1 이면 원본과 동일", () => {
    const coords = [
      [127.0, 37.0],
      [127.1, 37.0],
      [127.05, 37.1],
    ];
    expect(scaleCoords(coords, 1)).toEqual(coords);
  });
});

describe("nextOrbitRange", () => {
  it("확대(delta<0)는 궤도 거리를 줄인다", () => {
    // Arrange
    const current = 1000;

    // Act
    const next = nextOrbitRange(current, -1);

    // Assert
    expect(next).toBeCloseTo(current / ZOOM_STEP, 6);
  });

  it("축소(delta>0)는 궤도 거리를 늘린다", () => {
    // Arrange
    const current = 1000;

    // Act
    const next = nextOrbitRange(current, 1);

    // Assert
    expect(next).toBeCloseTo(current * ZOOM_STEP, 6);
  });

  it("확대해도 하한 150m 아래로 내려가지 않는다", () => {
    // Arrange
    const current = ZOOM_MIN_RANGE_M + 10;

    // Act
    const next = nextOrbitRange(current, -1);

    // Assert
    expect(next).toBe(ZOOM_MIN_RANGE_M);
  });

  it("축소해도 상한 4000m 를 넘지 않는다", () => {
    // Arrange
    const current = ZOOM_MAX_RANGE_M - 10;

    // Act
    const next = nextOrbitRange(current, 1);

    // Assert
    expect(next).toBe(ZOOM_MAX_RANGE_M);
  });

  it("NaN·무한대·0 이하 입력은 하한으로 폴백한다", () => {
    expect(nextOrbitRange(Number.NaN, -1)).toBe(ZOOM_MIN_RANGE_M);
    expect(nextOrbitRange(Number.POSITIVE_INFINITY, 1)).toBe(ZOOM_MIN_RANGE_M);
    expect(nextOrbitRange(0, -1)).toBe(ZOOM_MIN_RANGE_M);
    expect(nextOrbitRange(-500, 1)).toBe(ZOOM_MIN_RANGE_M);
  });
});
