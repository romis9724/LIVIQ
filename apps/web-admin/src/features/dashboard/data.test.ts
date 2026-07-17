import { describe, it, expect } from "vitest";

import { barWidth, budgetWidth, formatCount, formatPercent, formatTokens } from "./data";

describe("formatPercent (0~1 분수 → %)", () => {
  it("분수를 반올림 % 로 표기", () => {
    expect(formatPercent(2 / 3)).toBe("67%");
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(1)).toBe("100%");
  });

  it("null(분모 0)은 대시로 표기 — 지어내지 않음", () => {
    expect(formatPercent(null)).toBe("—");
  });
});

describe("formatTokens", () => {
  it("평균 토큰을 반올림 정수·천단위 구분", () => {
    expect(formatTokens(200)).toBe("200");
    expect(formatTokens(1234.6)).toBe("1,235");
  });

  it("null 은 대시", () => {
    expect(formatTokens(null)).toBe("—");
  });
});

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
