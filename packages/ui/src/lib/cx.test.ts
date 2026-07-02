import { describe, it, expect } from "vitest";

import { cx } from "./cx";

describe("cx", () => {
  it("truthy className을 공백으로 결합한다", () => {
    // Arrange / Act / Assert
    expect(cx("a", "b", "c")).toBe("a b c");
  });

  it("falsy 값(false·null·undefined)을 무시한다", () => {
    expect(cx("a", false, null, undefined, "b")).toBe("a b");
  });

  it("모두 falsy면 빈 문자열을 반환한다", () => {
    expect(cx(false, null, undefined)).toBe("");
  });

  it("인자가 없으면 빈 문자열을 반환한다", () => {
    expect(cx()).toBe("");
  });
});
