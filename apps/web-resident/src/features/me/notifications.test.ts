import { describe, it, expect } from "vitest";

import type { AppNotification } from "@/lib/api";
import {
  isUnread,
  markReadInList,
  notificationDate,
  notificationIcon,
  unreadCount,
} from "./notifications";

function notification(overrides: Partial<AppNotification>): AppNotification {
  return {
    id: overrides.id ?? "n",
    type: overrides.type ?? "system",
    title: overrides.title ?? "알림",
    body: overrides.body ?? null,
    link: overrides.link ?? null,
    readAt: overrides.readAt ?? null,
    createdAt: overrides.createdAt ?? "2026-07-01T00:00:00Z",
  };
}

describe("notificationIcon", () => {
  it("유형별 아이콘을 반환한다", () => {
    expect(notificationIcon("notice")).toBe("📢");
    expect(notificationIcon("inquiry_status")).toBe("🛠");
    expect(notificationIcon("approval")).toBe("✅");
    expect(notificationIcon("system")).toBe("🔔");
  });
});

describe("notificationDate", () => {
  it("ISO를 M/D로 표기한다", () => {
    expect(notificationDate("2026-07-03T09:00:00Z")).toBe("7/3");
  });

  it("파싱 실패는 빈 문자열", () => {
    expect(notificationDate("not-a-date")).toBe("");
  });
});

describe("isUnread / unreadCount", () => {
  it("readAt null 이면 미읽음", () => {
    expect(isUnread(notification({ readAt: null }))).toBe(true);
    expect(isUnread(notification({ readAt: "2026-07-02T00:00:00Z" }))).toBe(false);
  });

  it("미읽음 개수를 센다", () => {
    const items = [
      notification({ id: "a", readAt: null }),
      notification({ id: "b", readAt: "2026-07-02T00:00:00Z" }),
      notification({ id: "c", readAt: null }),
    ];
    expect(unreadCount(items)).toBe(2);
  });
});

describe("markReadInList", () => {
  it("대상 알림에 readAt을 채우고 원본을 변형하지 않는다", () => {
    const items = [
      notification({ id: "a", readAt: null }),
      notification({ id: "b", readAt: null }),
    ];
    const next = markReadInList(items, "a", "2026-07-05T00:00:00Z");
    expect(next.find((n) => n.id === "a")?.readAt).toBe("2026-07-05T00:00:00Z");
    expect(next.find((n) => n.id === "b")?.readAt).toBeNull();
    expect(items[0]?.readAt).toBeNull(); // 원본 불변
  });

  it("이미 읽은 알림은 시각을 유지한다(멱등)", () => {
    const items = [notification({ id: "a", readAt: "2026-07-01T00:00:00Z" })];
    const next = markReadInList(items, "a", "2026-07-09T00:00:00Z");
    expect(next[0]?.readAt).toBe("2026-07-01T00:00:00Z");
  });
});
