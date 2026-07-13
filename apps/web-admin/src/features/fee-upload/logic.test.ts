import { describe, it, expect } from "vitest";

import {
  HOUSEHOLDS,
  HOUSEHOLD_COUNT,
  feeSummary,
  percentDelta,
  validateUpload,
  previewRows,
  latestRecord,
  lookupHouseholds,
  formatWon,
  monthLabel,
} from "./logic";

describe("파일럿 세대 데이터 (101~103동 × 15층 × 2호)", () => {
  it("정확히 90세대를 결정적으로 생성한다", () => {
    expect(HOUSEHOLD_COUNT).toBe(90);
    expect(HOUSEHOLDS).toHaveLength(90);
  });

  it("동은 101~103, 호는 층·호 조합만 존재한다", () => {
    const dongs = new Set(HOUSEHOLDS.map((h) => h.dong));
    expect([...dongs].sort()).toEqual(["101", "102", "103"]);
    expect(HOUSEHOLDS.some((h) => h.ho === "1502")).toBe(true);
    expect(HOUSEHOLDS.some((h) => h.ho === "101")).toBe(true);
  });

  it("세대 total은 항목 금액의 합과 일치한다", () => {
    for (const h of HOUSEHOLDS) {
      const sum = Object.values(h.items).reduce((a, b) => a + b, 0);
      expect(h.total).toBe(sum);
    }
  });
});

describe("feeSummary — 합계·평균 계산", () => {
  it("합계는 세대 total의 총합, 평균은 합계/세대수(반올림)", () => {
    const rows = HOUSEHOLDS.slice(0, 3);
    const expectedTotal = rows.reduce((sum, h) => sum + h.total, 0);
    const s = feeSummary(rows);
    expect(s.count).toBe(3);
    expect(s.total).toBe(expectedTotal);
    expect(s.average).toBe(Math.round(expectedTotal / 3));
  });

  it("빈 목록은 합계·평균 0", () => {
    expect(feeSummary([])).toEqual({ count: 0, total: 0, average: 0 });
  });
});

describe("percentDelta — 전월 대비", () => {
  it("증가율을 반올림 정수 %로 반환", () => {
    expect(percentDelta(103, 100)).toBe(3);
    expect(percentDelta(90, 100)).toBe(-10);
  });

  it("이전값 0이면 0(0 나눗셈 방지)", () => {
    expect(percentDelta(100, 0)).toBe(0);
  });
});

describe("validateUpload — 데모 분기", () => {
  it("정상 파일은 ok=true, 90세대 통과, 오류 없음", () => {
    const r = validateUpload("관리비_2026-07.xlsx");
    expect(r.ok).toBe(true);
    expect(r.validatedCount).toBe(90);
    expect(r.missingCount).toBe(0);
    expect(r.issues).toHaveLength(0);
  });

  it("파일명에 'error' 포함 시 ok=false + 오류 리포트 + 누락 세대", () => {
    const r = validateUpload("관리비_error.xlsx");
    expect(r.ok).toBe(false);
    expect(r.missingCount).toBe(2);
    expect(r.issues.length).toBeGreaterThan(0);
    // 리포트 각 행은 행번호·컬럼·사유를 갖는다
    for (const issue of r.issues) {
      expect(typeof issue.row).toBe("number");
      expect(issue.column.length).toBeGreaterThan(0);
      expect(issue.reason.length).toBeGreaterThan(0);
    }
  });

  it("대소문자 무관하게 'ERROR'도 오류로 분기", () => {
    expect(validateUpload("BAD_ERROR.xlsx").ok).toBe(false);
  });
});

describe("previewRows / lookupHouseholds / latestRecord", () => {
  it("미리보기는 상위 5행만 반환", () => {
    expect(previewRows(HOUSEHOLDS)).toHaveLength(5);
    expect(previewRows(HOUSEHOLDS, 3)).toHaveLength(3);
  });

  it("동 필터는 해당 동만, 호 필터는 끝 2자리로 좁힌다", () => {
    const only101 = lookupHouseholds("101", "all", 100);
    expect(only101.every((h) => h.dong === "101")).toBe(true);
    expect(only101).toHaveLength(30); // 15층 × 2호

    const unit02 = lookupHouseholds("all", "02", 100);
    expect(unit02.every((h) => h.ho.endsWith("02"))).toBe(true);
  });

  it("latestRecord는 같은 달 최고 revision을 돌려주고, 미존재 월은 undefined", () => {
    expect(latestRecord("2026-07")?.revision).toBe(2);
    expect(latestRecord("2026-04")).toBeUndefined();
  });
});

describe("포매터", () => {
  it("formatWon은 천단위 구분 + '원'", () => {
    expect(formatWon(218000)).toBe("218,000원");
    expect(formatWon(0)).toBe("0원");
  });

  it("monthLabel은 한국어 연·월", () => {
    expect(monthLabel("2026-07")).toBe("2026년 7월");
  });
});
