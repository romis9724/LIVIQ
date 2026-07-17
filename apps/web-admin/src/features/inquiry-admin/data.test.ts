import { describe, it, expect } from "vitest";

import type { Inquiry } from "@/lib/api";
import { countByStatus, nextStatuses, shortDate } from "./data";

function inquiry(overrides: Partial<Inquiry>): Inquiry {
  return {
    id: overrides.id ?? "id",
    title: overrides.title ?? "제목",
    body: overrides.body ?? "내용",
    status: overrides.status ?? "received",
    aiPriority: overrides.aiPriority ?? "normal",
    categoryId: overrides.categoryId ?? null,
    aiSuggestedCategoryId: overrides.aiSuggestedCategoryId ?? null,
    assigneeUserId: overrides.assigneeUserId ?? null,
    authorUserId: overrides.authorUserId ?? "author",
    createdAt: overrides.createdAt ?? "2026-06-01T00:00:00Z",
  };
}

describe("countByStatus", () => {
  it("전체·상태별 개수를 집계한다", () => {
    const rows = [
      inquiry({ id: "1", status: "received" }),
      inquiry({ id: "2", status: "assigned" }),
      inquiry({ id: "3", status: "assigned" }),
      inquiry({ id: "4", status: "done" }),
    ];
    expect(countByStatus(rows)).toEqual({
      all: 4,
      received: 1,
      assigned: 2,
      in_progress: 0,
      done: 1,
    });
  });

  it("빈 목록은 모두 0", () => {
    expect(countByStatus([])).toEqual({
      all: 0,
      received: 0,
      assigned: 0,
      in_progress: 0,
      done: 0,
    });
  });
});

describe("nextStatuses", () => {
  it("현 상태 이후의 전진 상태만 반환한다", () => {
    expect(nextStatuses("received")).toEqual(["assigned", "in_progress", "done"]);
    expect(nextStatuses("in_progress")).toEqual(["done"]);
  });

  it("done 은 다음 상태가 없다", () => {
    expect(nextStatuses("done")).toEqual([]);
  });
});

describe("shortDate", () => {
  it("ISO → MM/DD", () => {
    expect(shortDate("2026-06-01T09:30:00Z")).toMatch(/^0[56]\/\d{2}$/);
  });

  it("잘못된 값은 대시", () => {
    expect(shortDate("nonsense")).toBe("—");
  });
});
