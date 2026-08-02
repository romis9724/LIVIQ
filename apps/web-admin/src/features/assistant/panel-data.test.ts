import { describe, expect, it } from "vitest";

import type { Inquiry, InquiryStatus } from "@/lib/api";
import { countByStatus } from "@/features/inquiry-admin/data";
import { pillKind, recentInquiries, relativeDay, statusRows } from "./panel-data";

function inquiry(id: string, createdAt: string, status: InquiryStatus = "received"): Inquiry {
  return {
    id,
    title: `민원 ${id}`,
    body: "",
    status,
    priority: null,
    categoryCodeId: null,
    assigneeUserId: null,
    authorUserId: "u1",
    createdAt,
    facilityId: null,
    facilityName: null,
  };
}

describe("statusRows", () => {
  it("접수·배정·처리중·완료 4줄을 순서대로 만든다", () => {
    const rows = statusRows(countByStatus([inquiry("a", "2026-08-01T00:00:00Z")]));
    expect(rows.map((r) => r.status)).toEqual(["received", "assigned", "in_progress", "done"]);
    expect(rows.map((r) => r.label)).toEqual(["미배정", "배정됨", "처리중", "완료"]);
  });

  it("재확인(reopened)은 1건이라도 있을 때만 줄을 만든다", () => {
    const counts = countByStatus([inquiry("a", "2026-08-01T00:00:00Z", "reopened")]);
    expect(statusRows(counts).map((r) => r.status)).toContain("reopened");
  });

  it("미배정·처리중만 0건이 아닐 때 강조한다", () => {
    const rows = statusRows(
      countByStatus([
        inquiry("a", "2026-08-01T00:00:00Z", "received"),
        inquiry("b", "2026-08-01T00:00:00Z", "assigned"),
        inquiry("c", "2026-08-01T00:00:00Z", "in_progress"),
      ]),
    );
    expect(rows.filter((r) => r.alert).map((r) => r.status)).toEqual(["received", "in_progress"]);
  });

  it("0건이면 강조하지 않는다", () => {
    expect(statusRows(countByStatus([])).some((r) => r.alert)).toBe(false);
  });
});

describe("recentInquiries", () => {
  it("생성일 내림차순으로 limit 건만 돌려준다", () => {
    const items = [
      inquiry("old", "2026-07-01T09:00:00Z"),
      inquiry("new", "2026-08-02T09:00:00Z"),
      inquiry("mid", "2026-07-20T09:00:00Z"),
    ];
    expect(recentInquiries(items, 2).map((i) => i.id)).toEqual(["new", "mid"]);
  });

  it("원본 배열을 정렬하지 않는다(불변)", () => {
    const items = [inquiry("a", "2026-07-01T09:00:00Z"), inquiry("b", "2026-08-02T09:00:00Z")];
    recentInquiries(items, 5);
    expect(items.map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("건수가 limit 보다 적으면 있는 만큼", () => {
    expect(recentInquiries([], 5)).toEqual([]);
  });
});

describe("relativeDay", () => {
  const now = new Date(2026, 7, 2, 14, 0, 0);

  it("같은 날은 '오늘', 하루 전은 '어제'", () => {
    expect(relativeDay(new Date(2026, 7, 2, 1, 0, 0).toISOString(), now)).toBe("오늘");
    expect(relativeDay(new Date(2026, 7, 1, 23, 0, 0).toISOString(), now)).toBe("어제");
  });

  it("일주일 안쪽은 'N일 전'", () => {
    expect(relativeDay(new Date(2026, 6, 29).toISOString(), now)).toBe("4일 전");
    expect(relativeDay(new Date(2026, 6, 26).toISOString(), now)).toBe("7일 전");
  });

  it("일주일을 넘기면 MM/DD", () => {
    expect(relativeDay(new Date(2026, 6, 25).toISOString(), now)).toBe("07/25");
  });

  it("파싱 실패는 대시 — 지어내지 않는다", () => {
    expect(relativeDay("어제쯤", now)).toBe("—");
  });
});

describe("pillKind", () => {
  it("민원 5상태를 StatusPill 4종에 접어 넣는다", () => {
    expect(pillKind("received")).toBe("received");
    expect(pillKind("assigned")).toBe("received");
    expect(pillKind("in_progress")).toBe("progress");
    expect(pillKind("reopened")).toBe("progress");
    expect(pillKind("done")).toBe("done");
  });
});
