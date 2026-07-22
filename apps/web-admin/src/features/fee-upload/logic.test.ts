import { describe, it, expect } from "vitest";

import type { FeeBreakdownRow } from "@/lib/api";
import { buildInvoice, formatWon, groupDigits, monthLabel, unitLabel } from "./logic";

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

describe("buildInvoice — 고지서 트리 구성", () => {
  const sample: FeeBreakdownRow[] = [
    { name: "공용관리비", level: 0, amount: 81468 },
    { name: "일반관리비", level: 1, amount: 42178 },
    { name: "급여", level: 3, amount: 27214 }, // level 3 → 접힘
    { name: "개별사용료", level: 0, amount: 83102 },
    { name: "수도 공용", level: 2, amount: -273 },
    { name: "장기수선충당금 월부과액", level: 0, amount: 12030 },
    { name: "충당금잔액", level: 1, amount: 407138 }, // 숨김
    { name: "적립요율(%)", level: 1, amount: 0 }, // 숨김
    { name: "합계", level: 0, amount: 176601 },
    { name: "잡수입", level: 0, amount: 2770 },
    { name: "공동기여수익", level: 1, amount: 2770 },
  ];
  const invoice = buildInvoice(sample);

  it("대분류를 그룹으로 묶는다(합계·잡수입 제외)", () => {
    expect(invoice.groups.map((g) => g.name)).toEqual([
      "공용관리비",
      "개별사용료",
      "장기수선충당금 월부과액",
    ]);
  });

  it("합계는 별도 강조 행", () => {
    expect(invoice.total?.amount).toBe(176601);
  });

  it("level 3 세부·충당금잔액·적립요율(%)은 숨긴다", () => {
    expect(invoice.groups[0]?.rows.map((r) => r.name)).toEqual(["일반관리비"]);
    expect(invoice.groups[2]?.rows).toEqual([]);
  });

  it("잡수입은 참고 섹션·음수 항목 유지", () => {
    expect(invoice.info?.rows.map((r) => r.name)).toEqual(["공동기여수익"]);
    expect(invoice.groups[1]?.rows[0]?.amount).toBe(-273);
  });

  it("빈 목록은 빈 고지서", () => {
    expect(buildInvoice([])).toEqual({ groups: [], total: null, info: null });
  });
});
