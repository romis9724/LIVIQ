import { describe, it, expect } from "vitest";

import type { AppNotification, Inquiry, Notice } from "@/lib/api";
import {
  HOME_NOTICE_LIMIT,
  currentPeriod,
  greeting,
  periodLabel,
  recentInquiry,
  recentNotices,
  unreadCount,
} from "./logic";

const notice = (over: Partial<Notice>): Notice => ({
  id: "n",
  title: "공지",
  body: "본문",
  audience: "ALL",
  pinned: false,
  publishedAt: "2026-07-10T00:00:00Z",
  createdAt: "2026-07-10T00:00:00Z",
  attachments: [],
  ...over,
});

describe("recentNotices", () => {
  it("발행 최신순 상위 N건만 반환한다", () => {
    const result = recentNotices(
      [
        notice({ id: "a", publishedAt: "2026-07-01T00:00:00Z" }),
        notice({ id: "b", publishedAt: "2026-07-15T00:00:00Z" }),
        notice({ id: "c", publishedAt: "2026-07-10T00:00:00Z" }),
        notice({ id: "d", publishedAt: "2026-07-20T00:00:00Z" }),
      ],
      2,
    );
    expect(result.map((n) => n.id)).toEqual(["d", "b"]);
  });

  it("published_at 이 없으면 created_at 으로 정렬한다", () => {
    const result = recentNotices([
      notice({ id: "a", publishedAt: null, createdAt: "2026-07-01T00:00:00Z" }),
      notice({ id: "b", publishedAt: null, createdAt: "2026-07-09T00:00:00Z" }),
    ]);
    expect(result[0]?.id).toBe("b");
  });

  it("기본 한도는 3건", () => {
    expect(HOME_NOTICE_LIMIT).toBe(3);
    const many = Array.from({ length: 5 }, (_, i) => notice({ id: `n${i}` }));
    expect(recentNotices(many)).toHaveLength(3);
  });

  it("빈 목록은 빈 배열", () => {
    expect(recentNotices([])).toEqual([]);
  });
});

describe("unreadCount", () => {
  const notif = (readAt: string | null): AppNotification => ({
    id: Math.random().toString(),
    type: "notice",
    title: "t",
    body: null,
    link: null,
    readAt,
    createdAt: "2026-07-10T00:00:00Z",
  });

  it("read_at 이 null 인 알림만 센다", () => {
    expect(unreadCount([notif(null), notif("2026-07-11T00:00:00Z"), notif(null)])).toBe(2);
  });

  it("모두 읽었으면 0", () => {
    expect(unreadCount([notif("2026-07-11T00:00:00Z")])).toBe(0);
  });
});

describe("recentInquiry", () => {
  const inquiry = (id: string, updatedAt: string): Inquiry => ({
    id,
    title: "민원",
    body: "본문",
    status: "received",
    aiPriority: null,
    categoryId: null,
    aiSuggestedCategoryId: null,
    assigneeUserId: null,
    authorUserId: "u",
    createdAt: updatedAt,
    updatedAt,
  });

  it("가장 최근 갱신된 민원을 반환한다", () => {
    const result = recentInquiry([
      inquiry("a", "2026-07-01T00:00:00Z"),
      inquiry("b", "2026-07-15T00:00:00Z"),
    ]);
    expect(result?.id).toBe("b");
  });

  it("민원이 없으면 null", () => {
    expect(recentInquiry([])).toBeNull();
  });
});

describe("currentPeriod / periodLabel", () => {
  it("YYYY-MM 형식으로 이번 달을 만든다(1자리 월 zero-pad)", () => {
    expect(currentPeriod(new Date(2026, 2, 9))).toBe("2026-03");
    expect(currentPeriod(new Date(2026, 11, 1))).toBe("2026-12");
  });

  it("YYYY-MM → YYYY.MM 표기", () => {
    expect(periodLabel("2026-07")).toBe("2026.07");
  });
});

describe("greeting", () => {
  it("이름이 있으면 이름만 노출한다(세대는 별도 표기)", () => {
    expect(greeting("최주민")).toBe("안녕하세요, 최주민님");
  });

  it("이름이 없으면 기본 인사말", () => {
    expect(greeting(null)).toBe("안녕하세요");
  });
});
