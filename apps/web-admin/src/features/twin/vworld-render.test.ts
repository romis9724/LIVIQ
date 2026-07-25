import { describe, expect, it } from "vitest";

import type { TwinGeometryItem } from "@/lib/api";
import { centerOf, scaleCoords } from "./vworld-render";

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
