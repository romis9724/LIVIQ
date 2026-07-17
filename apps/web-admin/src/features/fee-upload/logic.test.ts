import { describe, it, expect } from "vitest";

import { breakdownColumns, formatWon, groupDigits, monthLabel, unitLabel } from "./logic";

describe("포매터", () => {
  it("groupDigits는 천단위 구분을 넣는다", () => {
    expect(groupDigits(218000)).toBe("218,000");
    expect(groupDigits(0)).toBe("0");
    expect(groupDigits(1234567)).toBe("1,234,567");
  });

  it("formatWon은 천단위 구분 + '원'", () => {
    expect(formatWon(218000)).toBe("218,000원");
    expect(formatWon(0)).toBe("0원");
  });

  it("monthLabel은 한국어 연·월", () => {
    expect(monthLabel("2026-07")).toBe("2026년 7월");
    expect(monthLabel("2026-01")).toBe("2026년 1월");
  });

  it("unitLabel은 완전한 호수를 그대로 표기(층과 합성 금지)", () => {
    expect(unitLabel(10, 1001)).toBe("1001호");
    expect(unitLabel(15, 1502)).toBe("1502호");
  });
});

describe("breakdownColumns — 미리보기 항목 컬럼 수집", () => {
  it("여러 행의 항목 키를 합집합으로 수집한다", () => {
    const cols = breakdownColumns([
      { breakdown: { 일반관리비: 62000, 난방비: 73000 } },
      { breakdown: { 일반관리비: 61000, 수도료: 15000 } },
    ]);
    expect(cols).toContain("일반관리비");
    expect(cols).toContain("난방비");
    expect(cols).toContain("수도료");
    expect(cols).toHaveLength(3);
  });

  it("빈 목록은 빈 배열", () => {
    expect(breakdownColumns([])).toEqual([]);
  });
});
