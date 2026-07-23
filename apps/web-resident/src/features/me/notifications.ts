import type { AppNotification, NotificationType } from "@/lib/api";

// 알림 유형별 아이콘 — 인앱 함 시각 구분(디자인 이모지 어휘 재사용).
export const NOTIFICATION_ICON: Record<NotificationType, string> = {
  notice: "📢",
  inquiry_status: "🛠",
  approval: "✅",
  system: "🔔",
};

export function notificationIcon(type: NotificationType): string {
  return NOTIFICATION_ICON[type];
}

// created_at → "M/D" 짧은 표기. 파싱 실패는 빈 문자열(방어적).
export function notificationDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

// "나" 페이지 알림 요약에 노출할 최근 알림 개수. 나머지는 /notifications 전체 목록에서.
export const SUMMARY_LIMIT = 4;

export function summaryNotifications(items: readonly AppNotification[]): AppNotification[] {
  return items.slice(0, SUMMARY_LIMIT);
}

// 요약이 전부를 담지 못할 때만 "더보기" 노출 — 로드된 개수가 요약 상한을 넘으면 참.
export function hasMoreNotifications(items: readonly AppNotification[]): boolean {
  return items.length > SUMMARY_LIMIT;
}

export function isUnread(notification: AppNotification): boolean {
  return notification.readAt === null;
}

export function unreadCount(items: readonly AppNotification[]): number {
  return items.reduce((count, n) => (isUnread(n) ? count + 1 : count), 0);
}

// 읽음 토글 — 해당 id에 readAt 스탬프를 채운 새 배열 반환(불변). 이미 읽었으면 유지.
export function markReadInList(
  items: readonly AppNotification[],
  id: string,
  readAt: string,
): AppNotification[] {
  return items.map((n) => (n.id === id && n.readAt === null ? { ...n, readAt } : n));
}

// 삭제 — 해당 id를 제외한 새 배열 반환(불변). 낙관적 삭제·롤백에 사용.
export function removeFromList(
  items: readonly AppNotification[],
  id: string,
): AppNotification[] {
  return items.filter((n) => n.id !== id);
}
