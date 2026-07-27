import { describe, expect, it } from "vitest";
import {
  categoryColorVar,
  deviceCategory,
  distinctNonEmpty,
  markerLabel,
  normalizeUnitType,
  pixelFromClick,
  toPercent,
  toPixel,
} from "./floor-plan-admin-data";

describe("deviceCategory", () => {
  it("알려진 device_type을 카테고리로 매핑한다", () => {
    expect(deviceCategory("콘센트")).toBe("electric");
    expect(deviceCategory("월패드")).toBe("network");
    expect(deviceCategory("보일러")).toBe("water_heat");
    expect(deviceCategory("소화기")).toBe("safety");
  });

  it("미지 device_type은 '기타'", () => {
    expect(deviceCategory("알수없는기기")).toBe("other");
  });
});

describe("categoryColorVar", () => {
  it("카테고리마다 다른 CSS 변수명을 반환한다", () => {
    const vars = new Set(
      (["electric", "network", "water_heat", "safety", "other"] as const).map(categoryColorVar),
    );
    expect(vars.size).toBe(5);
    expect(categoryColorVar("electric")).toBe("--color-warning");
  });
});

describe("toPercent / toPixel", () => {
  it("픽셀 좌표를 컨테이너 대비 %로 변환한다", () => {
    expect(toPercent(461.5, 923)).toBeCloseTo(50, 5);
    expect(toPercent(0, 923)).toBe(0);
  });

  it("%를 픽셀로 되돌린다(반올림)", () => {
    expect(toPixel(50, 923)).toBe(462);
    expect(toPixel(0, 923)).toBe(0);
  });

  it("total이 0 이하이면 방어적으로 0을 반환한다", () => {
    expect(toPercent(10, 0)).toBe(0);
    expect(toPercent(10, -1)).toBe(0);
    expect(toPixel(10, 0)).toBe(0);
  });
});

describe("pixelFromClick", () => {
  it("컨테이너 기준 클릭 좌표를 원본 이미지 픽셀로 역변환한다", () => {
    expect(pixelFromClick(200, 100, 400, 200, 800, 400)).toEqual({ x: 400, y: 200 });
  });

  it("컨테이너 크기가 0 이하이면 방어적으로 {0,0}", () => {
    expect(pixelFromClick(10, 10, 0, 200, 800, 400)).toEqual({ x: 0, y: 0 });
  });
});

describe("distinctNonEmpty", () => {
  it("공백·중복을 제거하고 가나다 순 정렬한다", () => {
    expect(distinctNonEmpty(["거실", null, " ", "안방", "거실", undefined, "  주방 "])).toEqual([
      "거실",
      "안방",
      "주방",
    ]);
  });
});

describe("markerLabel", () => {
  it("방이 있으면 '방 종류' 형식이고 label이 있으면 덧붙인다", () => {
    expect(markerLabel({ room: "거실", deviceType: "콘센트", label: "냉장고용" })).toBe(
      "거실 콘센트 — 냉장고용",
    );
  });

  it("방·label이 없으면 종류만", () => {
    expect(markerLabel({ room: null, deviceType: "콘센트", label: null })).toBe("콘센트");
  });
});

describe("normalizeUnitType", () => {
  it("괄호 앞부분만 취해 트림한다", () => {
    expect(normalizeUnitType("84M(공공임대)")).toBe("84M");
    expect(normalizeUnitType(" 59C ")).toBe("59C");
  });

  it("null이거나 빈 값이면 null", () => {
    expect(normalizeUnitType(null)).toBeNull();
    expect(normalizeUnitType("   ")).toBeNull();
    expect(normalizeUnitType("(공공임대)")).toBeNull();
  });
});
