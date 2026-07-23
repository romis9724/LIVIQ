import { describe, it, expect } from "vitest";

import type { InquiryEvent } from "@/lib/api";
import {
  commentBody,
  commentKind,
  eventLabel,
  formatStatusChange,
  sortEvents,
  statusPill,
} from "./data";

function event(overrides: Partial<InquiryEvent>): InquiryEvent {
  return {
    id: overrides.id ?? "e",
    type: overrides.type ?? "created",
    actorUserId: overrides.actorUserId ?? null,
    payload: overrides.payload ?? null,
    createdAt: overrides.createdAt ?? "2026-06-01T00:00:00Z",
  };
}

describe("eventLabel", () => {
  it("타입별 한국어 라벨을 반환한다", () => {
    expect(eventLabel("created")).toBe("민원 접수됨");
    expect(eventLabel("ai_classified")).toBe("AI 분류");
    expect(eventLabel("assigned")).toBe("담당자 배정");
    expect(eventLabel("status_changed")).toBe("상태 변경");
  });
});

describe("statusPill", () => {
  it("실제 상태를 StatusPill 색상·라벨로 매핑한다", () => {
    expect(statusPill("received")).toEqual({ status: "received", label: "접수됨" });
    expect(statusPill("assigned")).toEqual({ status: "progress", label: "배정됨" });
    expect(statusPill("in_progress")).toEqual({ status: "progress", label: "처리중" });
    expect(statusPill("done")).toEqual({ status: "done", label: "완료" });
  });
});

describe("formatStatusChange", () => {
  it("from→to 를 라벨로 조립한다", () => {
    expect(formatStatusChange({ from: "received", to: "in_progress" })).toBe("접수됨 → 처리중");
  });

  it("from 없으면 to 라벨만", () => {
    expect(formatStatusChange({ to: "done" })).toBe("완료");
  });

  it("알 수 없는 코드는 원문 유지", () => {
    expect(formatStatusChange({ from: "x", to: "y" })).toBe("x → y");
  });

  it("payload 없거나 to 없으면 null", () => {
    expect(formatStatusChange(null)).toBeNull();
    expect(formatStatusChange({ from: "received" })).toBeNull();
  });
});

describe("commentKind", () => {
  it("reply·feedback kind 를 그대로 반환한다", () => {
    expect(commentKind({ kind: "reply", body: "확인했습니다" })).toBe("reply");
    expect(commentKind({ kind: "feedback", body: "감사합니다" })).toBe("feedback");
  });

  it("알 수 없는 kind·payload 없음이면 null", () => {
    expect(commentKind({ kind: "other" })).toBeNull();
    expect(commentKind({})).toBeNull();
    expect(commentKind(null)).toBeNull();
  });
});

describe("commentBody", () => {
  it("문자열 body 를 반환한다", () => {
    expect(commentBody({ kind: "reply", body: "처리 완료" })).toBe("처리 완료");
  });

  it("body 가 없거나 문자열이 아니면 빈 문자열", () => {
    expect(commentBody({ kind: "reply" })).toBe("");
    expect(commentBody({ body: 42 })).toBe("");
    expect(commentBody(null)).toBe("");
  });
});

describe("sortEvents", () => {
  it("created_at 오름차순으로 정렬하며 원본을 변형하지 않는다", () => {
    const input = [
      event({ id: "b", createdAt: "2026-06-03T00:00:00Z" }),
      event({ id: "a", createdAt: "2026-06-01T00:00:00Z" }),
      event({ id: "c", createdAt: "2026-06-02T00:00:00Z" }),
    ];
    expect(sortEvents(input).map((e) => e.id)).toEqual(["a", "c", "b"]);
    expect(input[0]?.id).toBe("b");
  });
});
