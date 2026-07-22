import { describe, it, expect } from "vitest";

import { formatDate, formatFileSize, toParagraphs } from "./data";

describe("formatDate", () => {
  it("ISO → YYYY.MM.DD", () => {
    expect(formatDate("2026-06-22T03:00:00Z")).toMatch(/^2026\.06\.2[12]$/);
  });

  it("null 은 빈 문자열", () => {
    expect(formatDate(null)).toBe("");
  });

  it("잘못된 값은 빈 문자열", () => {
    expect(formatDate("nonsense")).toBe("");
  });
});

describe("toParagraphs", () => {
  it("빈 줄 기준으로 문단을 나눈다", () => {
    expect(toParagraphs("첫 문단\n\n둘째 문단")).toEqual(["첫 문단", "둘째 문단"]);
  });

  it("문단 내 단일 줄바꿈은 유지한다", () => {
    expect(toParagraphs("· 일시: 6/22\n· 대상: 전 세대")).toEqual([
      "· 일시: 6/22\n· 대상: 전 세대",
    ]);
  });

  it("공백만 있는 문단은 제거한다", () => {
    expect(toParagraphs("본문\n\n   \n\n끝")).toEqual(["본문", "끝"]);
  });

  it("빈 본문은 빈 배열", () => {
    expect(toParagraphs("")).toEqual([]);
  });
});

describe("formatFileSize", () => {
  it("1024 미만은 바이트 단위", () => {
    expect(formatFileSize(0)).toBe("0B");
    expect(formatFileSize(940)).toBe("940B");
  });

  it("KB·MB·GB 로 승격하며 소수 1자리", () => {
    expect(formatFileSize(1536)).toBe("1.5KB");
    expect(formatFileSize(1.2 * 1024 * 1024)).toBe("1.2MB");
    expect(formatFileSize(3 * 1024 * 1024 * 1024)).toBe("3.0GB");
  });

  it("음수·비정상 값은 0B", () => {
    expect(formatFileSize(-5)).toBe("0B");
    expect(formatFileSize(Number.NaN)).toBe("0B");
  });
});
