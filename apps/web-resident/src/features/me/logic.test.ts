import { describe, it, expect } from "vitest";

import { accountStatusLabel, feePeriodLabel, roleLabel } from "./logic";

describe("roleLabel", () => {
  it("역할 코드를 한국어 라벨로 매핑한다", () => {
    expect(roleLabel(["RESIDENT"])).toBe("입주민");
    expect(roleLabel(["MANAGER"])).toBe("관리소장");
    expect(roleLabel(["STAFF"])).toBe("관리사무소 직원");
  });

  it("여러 역할 중 첫 역할을 대표로 쓴다", () => {
    expect(roleLabel(["MANAGER", "RESIDENT"])).toBe("관리소장");
  });

  it("매핑 없는 코드는 원문 유지", () => {
    expect(roleLabel(["UNKNOWN"])).toBe("UNKNOWN");
  });

  it("역할이 없으면 '회원'", () => {
    expect(roleLabel([])).toBe("회원");
  });
});

describe("accountStatusLabel", () => {
  it("상태 코드를 한국어로 매핑한다", () => {
    expect(accountStatusLabel("active")).toBe("활성 계정");
    expect(accountStatusLabel("pending")).toBe("승인 대기 중");
    expect(accountStatusLabel("inactive")).toBe("비활성 계정");
  });

  it("매핑 없는 상태는 원문 유지", () => {
    expect(accountStatusLabel("weird")).toBe("weird");
  });
});

describe("feePeriodLabel", () => {
  it("YYYY-MM → YYYY년 M월(선행 0 제거)", () => {
    expect(feePeriodLabel("2026-07")).toBe("2026년 7월");
    expect(feePeriodLabel("2026-12")).toBe("2026년 12월");
  });
});
