import { describe, expect, it } from "vitest";

import type { TwinGeometryItem } from "@/lib/api";
import {
  OCCUPANCY_COLORS,
  OCCUPANCY_LEGEND,
  boundsToViewState,
  colorForOverlay,
  computeBounds,
  legendForOverlay,
  occupancyColor,
  overlayValueText,
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

describe("colorForOverlay", () => {
  it("occupancy 는 occupancyColor 와 같고 undefined 는 공실 취급", () => {
    expect(colorForOverlay("occupancy", 0)).toEqual(OCCUPANCY_COLORS.vacant);
    expect(colorForOverlay("occupancy", undefined)).toEqual(OCCUPANCY_COLORS.vacant);
    expect(colorForOverlay("occupancy", 1)).toEqual(OCCUPANCY_COLORS.low);
    expect(colorForOverlay("occupancy", 3)).toEqual(OCCUPANCY_COLORS.high);
  });

  it("inquiries 0/undefined=중립 · 1~2=warning · 3+=danger", () => {
    const neutral = colorForOverlay("inquiries", 0);
    expect(colorForOverlay("inquiries", undefined)).toEqual(neutral);
    const warn = colorForOverlay("inquiries", 1);
    expect(colorForOverlay("inquiries", 2)).toEqual(warn); // 같은 밴드
    const danger = colorForOverlay("inquiries", 3);
    // 세 밴드가 서로 다른 색이어야 한다.
    expect(warn).not.toEqual(neutral);
    expect(danger).not.toEqual(warn);
    expect(colorForOverlay("inquiries", 9)).toEqual(danger);
  });

  it("fees undefined=중립 · 값 있으면 단일 accent(균등분배라 밴드 없이 동일)", () => {
    const none = colorForOverlay("fees", undefined);
    const billed = colorForOverlay("fees", 218000);
    expect(billed).not.toEqual(none);
    expect(colorForOverlay("fees", 999999)).toEqual(billed); // 값이 달라도 같은 accent
  });

  it("facilities 0=success · 1=check · 2=fault · 3=risk(모두 상이)", () => {
    const ok = colorForOverlay("facilities", 0);
    expect(colorForOverlay("facilities", undefined)).toEqual(ok);
    const check = colorForOverlay("facilities", 1);
    const fault = colorForOverlay("facilities", 2);
    const risk = colorForOverlay("facilities", 3);
    const bands = [ok, check, fault, risk].map((c) => c.join(","));
    expect(new Set(bands).size).toBe(4);
    expect(colorForOverlay("facilities", 5)).toEqual(risk); // 3 초과는 최악(risk)
  });
});

describe("legendForOverlay", () => {
  const labels = (kind: Parameters<typeof legendForOverlay>[0]) =>
    legendForOverlay(kind).map((e) => e.label);

  it("kind별 라벨 세트를 병기한다", () => {
    expect(labels("occupancy")).toEqual(["공실", "1~2인", "3인 이상"]);
    expect(labels("inquiries")).toEqual(["미종결 없음", "1~2건", "3건 이상"]);
    expect(labels("fees")).toEqual(["미부과", "부과됨"]);
    expect(labels("facilities")).toEqual(["정상", "점검 필요", "고장", "위험"]);
  });
});

describe("overlayValueText", () => {
  it("occupancy·inquiries 는 개수(undefined=0)", () => {
    expect(overlayValueText("occupancy", 3)).toBe("세대원 3명");
    expect(overlayValueText("occupancy", undefined)).toBe("세대원 0명");
    expect(overlayValueText("inquiries", 2)).toBe("미종결 2건");
    expect(overlayValueText("inquiries", undefined)).toBe("미종결 0건");
  });

  it("fees 는 금액·미부과", () => {
    expect(overlayValueText("fees", 218000)).toBe("218,000원");
    expect(overlayValueText("fees", undefined)).toBe("부과 내역 없음");
  });

  it("facilities 는 severity 라벨(undefined/0=정상 · 3+=위험)", () => {
    expect(overlayValueText("facilities", undefined)).toBe("정상");
    expect(overlayValueText("facilities", 0)).toBe("정상");
    expect(overlayValueText("facilities", 1)).toBe("점검 필요");
    expect(overlayValueText("facilities", 2)).toBe("고장");
    expect(overlayValueText("facilities", 3)).toBe("위험");
    expect(overlayValueText("facilities", 5)).toBe("위험");
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
