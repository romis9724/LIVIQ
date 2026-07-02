import { describe, it, expect } from "vitest";

import { RESIDENT_SCREENS, ADMIN_SCREENS, priorityColor } from "./screens";

describe("screens 카탈로그", () => {
  it("입주민 6 · 관리자 7 화면", () => {
    expect(RESIDENT_SCREENS).toHaveLength(6);
    expect(ADMIN_SCREENS).toHaveLength(7);
  });

  it("모든 href는 절대경로(/)로 시작한다", () => {
    for (const s of [...RESIDENT_SCREENS, ...ADMIN_SCREENS]) {
      expect(s.href.startsWith("/")).toBe(true);
    }
  });

  it("area 값이 카탈로그와 일치한다", () => {
    expect(RESIDENT_SCREENS.every((s) => s.area === "resident")).toBe(true);
    expect(ADMIN_SCREENS.every((s) => s.area === "admin")).toBe(true);
  });

  it("AI 비서·검수 큐는 P0 우선순위", () => {
    expect(RESIDENT_SCREENS.find((s) => s.href === "/assistant")?.priority).toBe("P0");
    expect(ADMIN_SCREENS.find((s) => s.href === "/admin/review-queue")?.priority).toBe("P0");
  });
});

describe("priorityColor", () => {
  it("P0는 accent 토큰", () => {
    expect(priorityColor("P0")).toBe("var(--color-accent)");
  });

  it("P2는 muted 토큰", () => {
    expect(priorityColor("P2")).toBe("var(--color-text-muted)");
  });

  it("모든 우선순위가 토큰 문자열을 반환한다", () => {
    for (const p of ["P0", "P1", "P2"] as const) {
      expect(priorityColor(p)).toContain("var(--color");
    }
  });
});
