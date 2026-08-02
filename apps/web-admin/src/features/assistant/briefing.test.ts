import { describe, expect, it } from "vitest";

import { briefingPrompt, isBriefingPrompt, isInquirySummaryAnswer, kstDateKey } from "./briefing";

describe("briefingPrompt", () => {
  it("오늘 날짜를 앞머리에 넣는다 — 8B 상대날짜 한계 보정", () => {
    expect(briefingPrompt(new Date(2026, 7, 2))).toMatch(/^오늘은 2026년 8월 2일입니다\. /);
  });

  it("한 자리 월·일은 0을 채우지 않는다", () => {
    expect(briefingPrompt(new Date(2026, 0, 9))).toContain("2026년 1월 9일");
  });

  it("인사·민원 요약·우선 처리 지시를 모두 담는다", () => {
    const prompt = briefingPrompt(new Date(2026, 7, 2));
    expect(prompt).toContain("인사");
    expect(prompt).toContain("민원 현황을 요약");
    expect(prompt).toContain("오늘 우선 처리해야 할 일");
  });
});

describe("isBriefingPrompt", () => {
  it("자기 자신이 만든 질문을 알아본다", () => {
    expect(isBriefingPrompt(briefingPrompt(new Date(2026, 7, 2)))).toBe(true);
  });

  it("날짜가 다른(복원된 어제) 브리핑도 알아본다 — 판정은 꼬리로만", () => {
    expect(isBriefingPrompt(briefingPrompt(new Date(2025, 11, 31)))).toBe(true);
  });

  it("사용자가 직접 친 질문은 브리핑이 아니다", () => {
    expect(isBriefingPrompt("오늘 미배정 민원 몇 건인가요?")).toBe(false);
    expect(isBriefingPrompt("")).toBe(false);
  });
});

describe("kstDateKey", () => {
  it("KST 날짜를 ISO 표기로 준다", () => {
    expect(kstDateKey(new Date("2026-08-02T03:00:00Z"))).toBe("2026-08-02");
  });

  it("UTC 15:00 이 KST 자정 — 그 직전까지는 같은 날", () => {
    expect(kstDateKey(new Date("2026-08-02T14:59:59Z"))).toBe("2026-08-02");
    expect(kstDateKey(new Date("2026-08-02T15:00:00Z"))).toBe("2026-08-03");
  });

  it("브라우저 시간대와 무관하게 KST 로 본다 — 연말 경계도 KST 기준", () => {
    expect(kstDateKey(new Date("2025-12-31T16:00:00Z"))).toBe("2026-01-01");
  });
});

describe("isInquirySummaryAnswer", () => {
  it("summarize_inquiries 가 라우팅된 답변에만 CTA", () => {
    expect(isInquirySummaryAnswer(["summarize_inquiries"])).toBe(true);
    expect(isInquirySummaryAnswer(["search_documents"])).toBe(false);
    expect(isInquirySummaryAnswer(undefined)).toBe(false);
  });
});
