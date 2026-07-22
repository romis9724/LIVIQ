import { describe, expect, it } from "vitest";
import { buildInvoice, type BreakdownRow } from "./invoice";

const SAMPLE: BreakdownRow[] = [
  { name: "공용관리비", level: 0, amount: 81468 },
  { name: "일반관리비", level: 1, amount: 42178 },
  { name: "인건비", level: 2, amount: 39433 },
  { name: "급여", level: 3, amount: 27214 }, // level 3 → 접힘
  { name: "개별사용료", level: 0, amount: 83102 },
  { name: "난방비", level: 1, amount: 13604 },
  { name: "수도 공용", level: 2, amount: -273 },
  { name: "장기수선충당금 월부과액", level: 0, amount: 12030 },
  { name: "월사용액", level: 1, amount: 1916 },
  { name: "충당금잔액", level: 1, amount: 407138 }, // 숨김
  { name: "적립요율(%)", level: 1, amount: 0 }, // 숨김
  { name: "합계", level: 0, amount: 176601 },
  { name: "잡수입", level: 0, amount: 2770 },
  { name: "공동기여수익", level: 1, amount: 2770 },
];

describe("buildInvoice — 고지서 트리 구성", () => {
  const invoice = buildInvoice(SAMPLE);

  it("대분류를 그룹으로 묶는다(합계·잡수입 제외)", () => {
    expect(invoice.groups.map((g) => g.name)).toEqual([
      "공용관리비",
      "개별사용료",
      "장기수선충당금 월부과액",
    ]);
  });

  it("합계는 별도 강조 행", () => {
    expect(invoice.total).toEqual({ name: "합계", level: 0, amount: 176601 });
  });

  it("잡수입은 참고 섹션으로 분리", () => {
    expect(invoice.info?.name).toBe("잡수입");
    expect(invoice.info?.rows.map((r) => r.name)).toEqual(["공동기여수익"]);
  });

  it("level 3 세부 항목은 접는다", () => {
    expect(invoice.groups[0]?.rows.map((r) => r.name)).toEqual(["일반관리비", "인건비"]);
  });

  it("충당금잔액·적립요율(%)은 숨긴다", () => {
    expect(invoice.groups[2]?.rows.map((r) => r.name)).toEqual(["월사용액"]);
  });

  it("음수 항목은 그대로 유지", () => {
    expect(invoice.groups[1]?.rows.find((r) => r.name === "수도 공용")?.amount).toBe(-273);
  });

  it("빈 리스트는 빈 고지서", () => {
    expect(buildInvoice([])).toEqual({ groups: [], total: null, info: null });
  });
});
