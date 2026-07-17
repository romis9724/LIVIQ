import { describe, it, expect } from "vitest";

import {
  confidenceLook,
  confidencePercent,
  displayableCitations,
  reviewTime,
} from "./data";

describe("confidenceLook 임계값(0~1 스케일)", () => {
  it("0.7 이상은 '보통'", () => {
    expect(confidenceLook(0.7).label).toBe("보통");
    expect(confidenceLook(0.95).label).toBe("보통");
  });

  it("0.5~0.69는 '낮음'", () => {
    expect(confidenceLook(0.5).label).toBe("낮음");
    expect(confidenceLook(0.69).label).toBe("낮음");
  });

  it("0.5 미만은 '매우 낮음' + danger 색", () => {
    expect(confidenceLook(0.34).label).toBe("매우 낮음");
    expect(confidenceLook(0).color).toBe("var(--color-danger)");
  });
});

describe("confidencePercent", () => {
  it("0~1 을 0~100 정수로 반올림", () => {
    expect(confidencePercent(0.62)).toBe(62);
    expect(confidencePercent(0.345)).toBe(35);
    expect(confidencePercent(1)).toBe(100);
  });

  it("null 은 null", () => {
    expect(confidencePercent(null)).toBeNull();
  });
});

describe("displayableCitations (절대규칙 1)", () => {
  it("문서명 없는 근거는 제외한다 — 지어내지 않음", () => {
    const result = displayableCitations([
      { documentTitle: "관리규약", quote: "제32조" },
      { documentTitle: null, quote: "fee_data" },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]!.documentTitle).toBe("관리규약");
  });
});

describe("reviewTime", () => {
  it("잘못된 ISO 는 대시", () => {
    expect(reviewTime("not-a-date")).toBe("—");
  });
});
