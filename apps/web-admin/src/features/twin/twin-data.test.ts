import { describe, expect, it } from "vitest";

import type { TwinGeometryItem } from "@/lib/api";
import {
  OCCUPANCY_COLORS,
  OCCUPANCY_LEGEND,
  boundsToViewState,
  computeBounds,
  occupancyColor,
  rgbCss,
} from "./twin-data";

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

describe("occupancyColor", () => {
  it("공실(0·음수)은 중립 회색", () => {
    expect(occupancyColor(0)).toEqual(OCCUPANCY_COLORS.vacant);
    expect(occupancyColor(-1)).toEqual(OCCUPANCY_COLORS.vacant);
  });

  it("1~2인은 옅은 블루", () => {
    expect(occupancyColor(1)).toEqual(OCCUPANCY_COLORS.low);
    expect(occupancyColor(2)).toEqual(OCCUPANCY_COLORS.low);
  });

  it("3인 이상은 진한 블루", () => {
    expect(occupancyColor(3)).toEqual(OCCUPANCY_COLORS.high);
    expect(occupancyColor(7)).toEqual(OCCUPANCY_COLORS.high);
  });
});

describe("OCCUPANCY_LEGEND · rgbCss", () => {
  it("범례는 색+텍스트 3구간을 병기한다", () => {
    expect(OCCUPANCY_LEGEND.map((e) => e.label)).toEqual(["공실", "1~2인", "3인 이상"]);
  });

  it("rgbCss는 CSS rgb 문자열을 만든다", () => {
    expect(rgbCss([12, 34, 56])).toBe("rgb(12 34 56)");
  });
});

describe("computeBounds", () => {
  it("모든 정점의 min/max 경위도를 구한다", () => {
    const items = [
      item([
        [127.0, 37.0],
        [127.2, 37.0],
        [127.2, 37.1],
      ]),
      item([
        [126.9, 36.95],
        [127.1, 37.05],
      ]),
    ];
    expect(computeBounds(items)).toEqual({
      minLng: 126.9,
      minLat: 36.95,
      maxLng: 127.2,
      maxLat: 37.1,
    });
  });

  it("정점이 없으면 null", () => {
    expect(computeBounds([])).toBeNull();
    expect(computeBounds([item([])])).toBeNull();
  });
});

describe("boundsToViewState", () => {
  it("중심은 bounds 중점", () => {
    const vs = boundsToViewState({ minLng: 127.0, minLat: 37.0, maxLng: 127.2, maxLat: 37.2 });
    expect(vs.longitude).toBeCloseTo(127.1, 6);
    expect(vs.latitude).toBeCloseTo(37.1, 6);
    expect(vs.zoom).toBeGreaterThanOrEqual(1);
    expect(vs.zoom).toBeLessThanOrEqual(20);
  });

  it("작은 span 은 큰 zoom, 큰 span 은 작은 zoom", () => {
    const tight = boundsToViewState({ minLng: 127.0, minLat: 37.0, maxLng: 127.001, maxLat: 37.001 });
    const wide = boundsToViewState({ minLng: 127.0, minLat: 37.0, maxLng: 128.0, maxLat: 38.0 });
    expect(tight.zoom).toBeGreaterThan(wide.zoom);
  });

  it("span 0(단일점)은 기본 확대율로 폴백", () => {
    const vs = boundsToViewState({ minLng: 127.0, minLat: 37.0, maxLng: 127.0, maxLat: 37.0 });
    expect(vs.zoom).toBe(18);
  });
});
