import { describe, it, expect } from "vitest";

import { addKeyword, canGenerate, confidenceStatus, removeKeyword } from "./data";

describe("addKeyword", () => {
  it("공백을 트림해 추가한다", () => {
    expect(addKeyword([], "  단수  ")).toEqual({ ok: true, keywords: ["단수"] });
  });

  it("빈 값은 거절한다", () => {
    expect(addKeyword([], "   ")).toEqual({ ok: false, reason: "empty" });
  });

  it("중복은 거절한다", () => {
    expect(addKeyword(["단수"], "단수")).toEqual({ ok: false, reason: "duplicate" });
  });

  it("10개를 초과하면 거절한다", () => {
    const full = Array.from({ length: 10 }, (_, i) => `k${i}`);
    expect(addKeyword(full, "k10")).toEqual({ ok: false, reason: "max" });
  });

  it("원본을 변형하지 않고 새 배열을 반환한다", () => {
    const original = ["단수"];
    const result = addKeyword(original, "배관");
    expect(original).toEqual(["단수"]);
    expect(result).toEqual({ ok: true, keywords: ["단수", "배관"] });
  });
});

describe("removeKeyword", () => {
  it("인덱스로 제거한다", () => {
    expect(removeKeyword(["a", "b", "c"], 1)).toEqual(["a", "c"]);
  });
});

describe("canGenerate", () => {
  it("1~10개면 true", () => {
    expect(canGenerate(["a"])).toBe(true);
    expect(canGenerate(Array.from({ length: 10 }, (_, i) => `k${i}`))).toBe(true);
  });

  it("0개면 false", () => {
    expect(canGenerate([])).toBe(false);
  });
});

describe("confidenceStatus", () => {
  it("임계값 이상은 answered", () => {
    expect(confidenceStatus(0.6)).toBe("answered");
    expect(confidenceStatus(0.9)).toBe("answered");
  });

  it("임계값 미만은 review", () => {
    expect(confidenceStatus(0.59)).toBe("review");
    expect(confidenceStatus(0)).toBe("review");
  });
});
