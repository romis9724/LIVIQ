import { describe, it, expect } from "vitest";

import type { Facility } from "@/lib/api";
import {
  STATUS_META,
  countByStatus,
  shortDate,
  validateFacilityName,
  validateRequiredText,
} from "./data";

function fac(status: Facility["status"]): Facility {
  return {
    id: crypto.randomUUID(),
    name: "설비",
    location: null,
    type: null,
    status,
    nextCheckAt: null,
    createdAt: "2026-07-01T00:00:00Z",
  };
}

describe("STATUS_META (normal→ok css 매핑)", () => {
  it("normal 은 css 'ok' 로 매핑해 기존 스타일을 재사용", () => {
    expect(STATUS_META.normal.css).toBe("ok");
    expect(STATUS_META.fault.label).toBe("장애");
  });
});

describe("countByStatus", () => {
  it("상태별 개수와 전체 개수를 집계", () => {
    const counts = countByStatus([fac("normal"), fac("normal"), fac("fault")]);
    expect(counts.all).toBe(3);
    expect(counts.normal).toBe(2);
    expect(counts.fault).toBe(1);
    expect(counts.risk).toBe(0);
  });
});

describe("validateFacilityName", () => {
  it("공백만 있으면 에러", () => {
    expect(validateFacilityName("   ")).not.toBeNull();
  });
  it("정상 이름은 null", () => {
    expect(validateFacilityName("승강기")).toBeNull();
  });
});

describe("validateRequiredText", () => {
  it("빈 값은 필드명을 포함한 에러", () => {
    expect(validateRequiredText("", "증상")).toContain("증상");
  });
  it("정상 값은 null", () => {
    expect(validateRequiredText("소음 발생", "증상")).toBeNull();
  });
});

describe("shortDate", () => {
  it("null·잘못된 값은 대시", () => {
    expect(shortDate(null)).toBe("—");
    expect(shortDate("nope")).toBe("—");
  });
  it("ISO 를 YYYY.MM.DD 로", () => {
    expect(shortDate("2026-07-01T00:00:00Z")).toMatch(/^2026\.07\.01$/);
  });
});
