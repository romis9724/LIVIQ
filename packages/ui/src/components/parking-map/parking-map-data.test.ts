import { describe, expect, it } from "vitest";
import { elapsedText, parseViewBox } from "./parking-map-data";

const NOW_MS = Date.parse("2026-08-01T12:00:00Z");

describe("parseViewBox", () => {
  it("splits a four-number viewBox", () => {
    expect(parseViewBox("0 0 3020 1082")).toEqual([0, 0, 3020, 1082]);
  });

  it("accepts comma separators and surrounding whitespace", () => {
    expect(parseViewBox("  -10, 5 , 100,50 ")).toEqual([-10, 5, 100, 50]);
  });

  it("falls back to 0 for missing or unparseable parts", () => {
    // 렌더가 깨지는 대신 0 으로 접는다(빈 배치도 = 크기 0 → 포커스 계산 생략).
    expect(parseViewBox("0 0")).toEqual([0, 0, 0, 0]);
    expect(parseViewBox("")).toEqual([0, 0, 0, 0]);
  });
});

describe("elapsedText", () => {
  it("formats hours and minutes", () => {
    expect(elapsedText(NOW_MS - (3 * 60 + 20) * 60_000, NOW_MS)).toBe("3시간 20분");
  });

  it("omits hours under one hour", () => {
    expect(elapsedText(NOW_MS - 45 * 60_000, NOW_MS)).toBe("45분");
  });

  it("clamps future entry times to 0분", () => {
    expect(elapsedText(NOW_MS + 60_000, NOW_MS)).toBe("0분");
  });
});
