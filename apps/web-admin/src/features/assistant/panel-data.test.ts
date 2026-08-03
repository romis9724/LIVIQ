import { describe, expect, it } from "vitest";

import type { Inquiry, InquiryEvent, InquiryStatus } from "@/lib/api";
import { countByStatus } from "@/features/inquiry-admin/data";
import {
  drilldownRows,
  excerpt,
  historyLines,
  pillKind,
  recentInquiries,
  relativeDay,
  statusRows,
} from "./panel-data";

function inquiry(
  id: string,
  createdAt: string,
  status: InquiryStatus = "received",
  updatedAt = createdAt,
): Inquiry {
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
    updatedAt,
    facilityId: null,
    facilityName: null,
  };
}

function event(
  id: string,
  type: InquiryEvent["type"],
  createdAt: string,
  payload: Record<string, unknown> | null = null,
): InquiryEvent {
  return { id, type, actorUserId: null, payload, createdAt };
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

describe("drilldownRows", () => {
  const now = new Date(2026, 7, 3, 10, 0, 0);
  const iso = (y: number, m: number, d: number): string => new Date(y, m, d, 9, 0, 0).toISOString();

  it("미완료 상태는 접수 오래된 순 + 접수일자·경과일", () => {
    const items = [
      inquiry("new", iso(2026, 7, 2), "received"),
      inquiry("old", iso(2026, 6, 20), "received"),
      inquiry("mid", iso(2026, 7, 1), "received"),
      inquiry("other", iso(2026, 6, 1), "done"),
    ];
    const rows = drilldownRows(items, "received", now);
    expect(rows.map((r) => r.inquiry.id)).toEqual(["old", "mid", "new"]);
    expect(rows[0]).toMatchObject({ dateKind: "received", dateLabel: "07/20", elapsedDays: 14 });
    expect(rows[2]?.elapsedDays).toBe(1);
  });

  it("완료 상태는 완료(updatedAt) 최신순 + 완료일자, 경과일 없음", () => {
    const items = [
      inquiry("a", iso(2026, 5, 1), "done", iso(2026, 5, 10)),
      inquiry("b", iso(2026, 5, 2), "done", iso(2026, 6, 30)),
    ];
    const rows = drilldownRows(items, "done", now);
    expect(rows.map((r) => r.inquiry.id)).toEqual(["b", "a"]);
    expect(rows[0]).toMatchObject({ dateKind: "completed", dateLabel: "07/30", elapsedDays: null });
  });

  it("접수 7일이 지난 미완료 건만 재촉 표식", () => {
    const items = [
      inquiry("fresh", iso(2026, 7, 1), "in_progress"),
      inquiry("stale", iso(2026, 6, 25), "in_progress"),
    ];
    const rows = drilldownRows(items, "in_progress", now);
    expect(rows.map((r) => r.overdue)).toEqual([true, false]);
  });

  it("원본 배열을 정렬하지 않는다(불변)", () => {
    const items = [inquiry("a", iso(2026, 7, 2)), inquiry("b", iso(2026, 6, 2))];
    drilldownRows(items, "received", now);
    expect(items.map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("해당 상태가 없으면 빈 목록", () => {
    expect(drilldownRows([inquiry("a", iso(2026, 7, 2))], "done", now)).toEqual([]);
  });
});

describe("historyLines", () => {
  it("시간순으로 접수·배정·상태 변경·답변을 한 줄씩 압축한다", () => {
    const lines = historyLines([
      event("e3", "comment", "2026-07-03T00:00:00Z", { kind: "reply", body: "부품 교체 완료" }),
      event("e1", "created", "2026-07-01T00:00:00Z"),
      event("e2", "status_changed", "2026-07-02T00:00:00Z", { from: "assigned", to: "done" }),
    ]);
    expect(lines.map((l) => l.id)).toEqual(["e1", "e2", "e3"]);
    expect(lines[1]?.text).toBe("상태 변경 · 배정됨 → 완료");
    expect(lines[2]?.text).toBe("담당자 답변 · 부품 교체 완료");
  });

  it("입주민 피드백과 담당자 답변을 구분한다", () => {
    const lines = historyLines([
      event("e1", "comment", "2026-07-01T00:00:00Z", { kind: "feedback", body: "아직 소리 나요" }),
    ]);
    expect(lines[0]?.text).toBe("입주민 피드백 · 아직 소리 나요");
  });

  it("본문이 길면 잘라서 한 줄로 만든다", () => {
    const lines = historyLines([
      event("e1", "comment", "2026-07-01T00:00:00Z", { kind: "reply", body: "가".repeat(200) }),
    ]);
    expect(lines[0]?.text.length ?? 0).toBeLessThan(120);
    expect(lines[0]?.text.endsWith("…")).toBe(true);
  });

  it("payload 가 없는 이벤트도 라벨만으로 한 줄", () => {
    const lines = historyLines([event("e1", "assigned", "2026-07-01T00:00:00Z")]);
    expect(lines[0]).toMatchObject({ text: "담당자 배정", date: "07/01" });
  });
});

describe("excerpt", () => {
  it("줄바꿈·연속 공백을 한 줄로 접는다", () => {
    expect(excerpt("첫 줄\n\n둘째   줄", 40)).toBe("첫 줄 둘째 줄");
  });

  it("상한을 넘으면 말줄임", () => {
    expect(excerpt("가".repeat(30), 10)).toBe(`${"가".repeat(10)}…`);
  });

  it("빈 값은 빈 문자열 — 지어내지 않는다", () => {
    expect(excerpt("   ", 10)).toBe("");
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
