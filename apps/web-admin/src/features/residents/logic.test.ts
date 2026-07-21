import { describe, it, expect } from "vitest";

import { ROSTER_MAX_BYTES, formatUnit, isValidRejectReason, validateRoster } from "./logic";

describe("validateRoster (경계 입력)", () => {
  it("xlsx 파일은 통과", () => {
    expect(validateRoster({ name: "roster.xlsx", size: 1024 })).toBeNull();
  });

  it("다른 확장자는 거절", () => {
    expect(validateRoster({ name: "roster.csv", size: 1024 })).toContain(".xlsx");
  });

  it("10MB 초과는 거절", () => {
    expect(validateRoster({ name: "roster.xlsx", size: ROSTER_MAX_BYTES + 1 })).toContain("MB");
  });
});

describe("isValidRejectReason (거절 사유 필수)", () => {
  it("내용이 있으면 통과", () => {
    expect(isValidRejectReason("명부 미등록 세대")).toBe(true);
  });

  it("공백만 있으면 거부", () => {
    expect(isValidRejectReason("   ")).toBe(false);
    expect(isValidRejectReason("")).toBe(false);
  });
});

describe("formatUnit (세대 표기)", () => {
  it("동·호를 결합한다", () => {
    expect(formatUnit("101", 1002)).toBe("101동 1002호");
  });

  it("일부만 있으면 남는 정보만 조합한다", () => {
    expect(formatUnit("103", null)).toBe("103동");
    expect(formatUnit(null, 301)).toBe("301호");
  });

  it("정보가 없으면 안내 문구", () => {
    expect(formatUnit(null, null)).toBe("세대 정보 없음");
  });
});
