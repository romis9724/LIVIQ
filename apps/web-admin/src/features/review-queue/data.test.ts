import { describe, it, expect } from "vitest";

import { REVIEW_ITEMS, confidenceLook } from "./data";

describe("confidenceLook 임계값", () => {
  it("70 이상은 '보통'", () => {
    expect(confidenceLook(70).label).toBe("보통");
    expect(confidenceLook(95).label).toBe("보통");
  });

  it("50~69는 '낮음'", () => {
    expect(confidenceLook(50).label).toBe("낮음");
    expect(confidenceLook(69).label).toBe("낮음");
  });

  it("50 미만은 '매우 낮음' + danger 색", () => {
    expect(confidenceLook(34).label).toBe("매우 낮음");
    expect(confidenceLook(0).color).toBe("var(--color-danger)");
  });
});

describe("REVIEW_ITEMS 무결성 (절대규칙 1)", () => {
  it("저신뢰(50 미만) 항목은 출처를 지어내지 않고 담당자 연결을 권한다", () => {
    const lowConf = REVIEW_ITEMS.filter((i) => i.confidence < 50);
    expect(lowConf.length).toBeGreaterThan(0);
    for (const item of lowConf) {
      // 근거 없으면 source 부재 + 담당자 연결 문구 (지어내지 않음)
      expect(item.source).toBeUndefined();
      expect(item.answer).toContain("담당자");
    }
  });

  it("confidence는 0~100 범위", () => {
    for (const item of REVIEW_ITEMS) {
      expect(item.confidence).toBeGreaterThanOrEqual(0);
      expect(item.confidence).toBeLessThanOrEqual(100);
    }
  });
});
