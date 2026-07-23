import { describe, it, expect } from "vitest";

import type { Inquiry, InquiryEvent } from "@/lib/api";
import {
  commentBody,
  commentKind,
  countByStatus,
  eventLabel,
  formatStatusChange,
  hasReply,
  shortDate,
  sortEvents,
} from "./data";

function inquiry(overrides: Partial<Inquiry>): Inquiry {
  return {
    id: overrides.id ?? "id",
    title: overrides.title ?? "제목",
    body: overrides.body ?? "내용",
    status: overrides.status ?? "received",
    priority: overrides.priority ?? "normal",
    categoryCodeId: overrides.categoryCodeId ?? null,
    assigneeUserId: overrides.assigneeUserId ?? null,
    authorUserId: overrides.authorUserId ?? "author",
    createdAt: overrides.createdAt ?? "2026-06-01T00:00:00Z",
  };
}

function event(overrides: Partial<InquiryEvent>): InquiryEvent {
  return {
    id: overrides.id ?? "ev",
    type: overrides.type ?? "created",
    actorUserId: overrides.actorUserId ?? null,
    payload: overrides.payload ?? null,
    createdAt: overrides.createdAt ?? "2026-06-01T00:00:00Z",
  };
}

describe("countByStatus", () => {
  it("전체·상태별 개수를 집계한다", () => {
    const rows = [
      inquiry({ id: "1", status: "received" }),
      inquiry({ id: "2", status: "assigned" }),
      inquiry({ id: "3", status: "assigned" }),
      inquiry({ id: "4", status: "reopened" }),
      inquiry({ id: "5", status: "done" }),
    ];
    expect(countByStatus(rows)).toEqual({
      all: 5,
      received: 1,
      assigned: 2,
      in_progress: 0,
      reopened: 1,
      done: 1,
    });
  });

  it("빈 목록은 모두 0", () => {
    expect(countByStatus([])).toEqual({
      all: 0,
      received: 0,
      assigned: 0,
      in_progress: 0,
      reopened: 0,
      done: 0,
    });
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

describe("eventLabel", () => {
  it("이벤트 타입을 한국어 라벨로", () => {
    expect(eventLabel("created")).toBe("민원 접수됨");
    expect(eventLabel("assigned")).toBe("담당자 배정");
  });
});

describe("formatStatusChange", () => {
  it("from·to 를 상태 라벨로 환산", () => {
    expect(formatStatusChange({ from: "received", to: "assigned" })).toBe("미배정 → 배정됨");
  });

  it("from 이 없으면 to 만", () => {
    expect(formatStatusChange({ to: "done" })).toBe("완료");
  });

  it("payload·to 없으면 null", () => {
    expect(formatStatusChange(null)).toBeNull();
    expect(formatStatusChange({ from: "received" })).toBeNull();
  });
});

describe("commentKind / commentBody", () => {
  it("kind·body 를 추출한다", () => {
    expect(commentKind({ kind: "reply", body: "답변" })).toBe("reply");
    expect(commentKind({ kind: "feedback" })).toBe("feedback");
    expect(commentBody({ kind: "reply", body: "답변" })).toBe("답변");
  });

  it("알 수 없는 kind·본문은 null·빈문자열", () => {
    expect(commentKind({ kind: "other" })).toBeNull();
    expect(commentKind(null)).toBeNull();
    expect(commentBody(null)).toBe("");
  });
});

describe("sortEvents", () => {
  it("created_at 오름차순 정렬(불변)", () => {
    const a = event({ id: "a", createdAt: "2026-06-02T00:00:00Z" });
    const b = event({ id: "b", createdAt: "2026-06-01T00:00:00Z" });
    const input = [a, b];
    const sorted = sortEvents(input);
    expect(sorted.map((e) => e.id)).toEqual(["b", "a"]);
    expect(input.map((e) => e.id)).toEqual(["a", "b"]); // 원본 불변
  });
});

describe("hasReply", () => {
  it("reply 코멘트가 있으면 true", () => {
    const events = [
      event({ type: "created" }),
      event({ type: "comment", payload: { kind: "reply", body: "답변" } }),
    ];
    expect(hasReply(events)).toBe(true);
  });

  it("feedback 만 있으면 false", () => {
    const events = [event({ type: "comment", payload: { kind: "feedback", body: "추가" } })];
    expect(hasReply(events)).toBe(false);
  });

  it("코멘트 없으면 false", () => {
    expect(hasReply([event({ type: "created" })])).toBe(false);
  });
});
