import { describe, it, expect } from "vitest";

import { barWidth, budgetWidth, formatCount } from "./data";

describe("formatCount", () => {
  it("천단위 구분", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(12345)).toBe("12,345");
  });
});

describe("barWidth (최대값 상대 폭)", () => {
  it("최대값은 100%, 나머지는 비례", () => {
    expect(barWidth(2, [2, 0, 0, 1])).toBe("100%");
    expect(barWidth(1, [2, 0, 0, 1])).toBe("50%");
  });

  it("전부 0이면 0%", () => {
    expect(barWidth(0, [0, 0, 0, 0])).toBe("0%");
  });
});

describe("budgetWidth (예산 사용 게이지)", () => {
  it("used/budget 비율 %", () => {
    expect(budgetWidth(2500, 10000)).toBe("25%");
    expect(budgetWidth(10000, 10000)).toBe("100%");
  });

  it("초과해도 100%로 클램프", () => {
    expect(budgetWidth(15000, 10000)).toBe("100%");
  });

  it("예산 0(비활성)이면 0%", () => {
    expect(budgetWidth(500, 0)).toBe("0%");
  });
});
