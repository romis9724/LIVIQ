// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { StructuredBlock } from "./StructuredBlock";
import { toStructured } from "./assistant-structured";

/** 서버(ai_core/tools/fees_compare.py `_compare_data`)가 실제로 보내는 형태. */
const COMPARE_PAYLOAD = {
  kind: "fee_compare",
  period: "2026-07",
  rows: [
    { label: "우리집", kind: "self", amount: 176601, sample_size: null, note: "" },
    { label: "단지 전체", kind: "complex", amount: 168211, sample_size: 322, note: "" },
    { label: "999동", kind: "dong", amount: null, sample_size: null, note: "관리비 데이터 없음" },
  ],
  base_label: "우리집",
  diffs: [{ label: "단지 전체", diff: 8390 }],
};

describe("StructuredBlock — fee_compare", () => {
  it("대상별 금액·표본과 차액을 서버 값 그대로 그린다", () => {
    // Arrange
    const data = toStructured(COMPARE_PAYLOAD);
    if (data === null) throw new Error("파싱 실패");

    // Act
    render(<StructuredBlock data={data} />);

    // Assert — 금액은 자릿수 구분만 붙고 다시 계산되지 않는다(규칙 5).
    expect(screen.getByText("2026-07 관리비 비교")).toBeDefined();
    expect(screen.getByText("176,601원")).toBeDefined();
    expect(screen.getByText("322세대")).toBeDefined();
    // 값을 못 낸 대상은 숨기지 않고 사유를 적는다(규칙 1).
    expect(screen.getByText("관리비 데이터 없음")).toBeDefined();
    // 증감은 색이 아니라 글자로(WCAG 1.4.1).
    expect(screen.getByText(/8,390원 많아요/)).toBeDefined();
  });
});
