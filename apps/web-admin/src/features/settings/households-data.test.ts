import { describe, it, expect } from "vitest";

import {
  BULK_MAX_HOUSEHOLDS,
  countCombos,
  previewLabels,
  unitLabel,
  validateRange,
} from "./households-data";

const ok = { floorStart: 1, floorEnd: 3, unitStart: 1, unitEnd: 2 };

describe("validateRange", () => {
  it("정상 범위는 통과", () => {
    expect(validateRange(ok)).toBeNull();
  });

  it("역순 층은 거절", () => {
    expect(validateRange({ ...ok, floorStart: 5, floorEnd: 1 })).toContain("끝 층");
  });

  it("역순 호는 거절", () => {
    expect(validateRange({ ...ok, unitStart: 3, unitEnd: 1 })).toContain("끝 호");
  });

  it("정수가 아니면 거절", () => {
    expect(validateRange({ ...ok, floorStart: 1.5 })).toContain("정수");
  });

  it("호 순번 범위를 벗어나면 거절", () => {
    expect(validateRange({ ...ok, unitEnd: 200 })).toContain("호 순번");
  });

  it("상한(2000) 초과는 거절", () => {
    expect(validateRange({ floorStart: 1, floorEnd: 200, unitStart: 1, unitEnd: 99 })).toContain(
      "최대",
    );
  });
});

describe("countCombos", () => {
  it("층 × 호 곱", () => {
    expect(countCombos(ok)).toBe(6); // 3층 × 2호
  });

  it("역순이면 0", () => {
    expect(countCombos({ floorStart: 3, floorEnd: 1, unitStart: 1, unitEnd: 1 })).toBe(0);
  });

  it("상한 조합 수", () => {
    expect(countCombos({ floorStart: 1, floorEnd: 200, unitStart: 1, unitEnd: 99 })).toBeGreaterThan(
      BULK_MAX_HOUSEHOLDS,
    );
  });
});

describe("unitLabel · previewLabels", () => {
  it("완전 호수를 그대로 표기(floor 미합성)", () => {
    expect(unitLabel(3, 301)).toBe("301호");
    expect(unitLabel(10, 1001)).toBe("1001호");
    // 버그였던 이중 합성 방지: unit_no 201을 "2201호"로 만들지 않는다.
    expect(unitLabel(2, 201)).toBe("201호");
  });

  it("미리보기는 순번을 완전 호수(floor*100+순번)로 변환", () => {
    // ok = 1~3층 × 순번 1~2 → 101·102·201…
    expect(previewLabels(ok, 3)).toEqual(["101호", "102호", "201호"]);
    // 10층 순번 1~3 → 1001·1002·1003.
    expect(previewLabels({ floorStart: 10, floorEnd: 10, unitStart: 1, unitEnd: 3 })).toEqual([
      "1001호",
      "1002호",
      "1003호",
    ]);
  });
});
