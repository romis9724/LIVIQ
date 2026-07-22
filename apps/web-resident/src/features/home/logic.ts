// 입주민 홈 순수 로직 — 실데이터 요약 변환. UI·네트워크 의존 없음(테스트 대상).

import type { AppNotification, Inquiry, Notice } from "@/lib/api";

/** 홈에 노출할 최신 공지 최대 건수. */
export const HOME_NOTICE_LIMIT = 3;

/** 발행 최신순 상위 N건. published_at 우선, 없으면 created_at 로 정렬(방어적). */
export function recentNotices(
  notices: readonly Notice[],
  limit: number = HOME_NOTICE_LIMIT,
): Notice[] {
  return [...notices]
    .sort((a, b) => (b.publishedAt ?? b.createdAt).localeCompare(a.publishedAt ?? a.createdAt))
    .slice(0, limit);
}

/** 미읽음(read_at null) 알림 수. */
export function unreadCount(notifications: readonly AppNotification[]): number {
  return notifications.filter((n) => n.readAt === null).length;
}

/** 가장 최근 갱신된 내 민원. 없으면 null. */
export function recentInquiry(inquiries: readonly Inquiry[]): Inquiry | null {
  return [...inquiries].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0] ?? null;
}

/** 이번 달(YYYY-MM). 관리비 조회 기본 월. */
export function currentPeriod(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** YYYY-MM → "YYYY.MM" 표기. */
export function periodLabel(period: string): string {
  return period.replace("-", ".");
}

/**
 * 홈 인사말. 실명·세대는 서버가 본인 vault만 복호해 내려준 값(마스킹 대상 아님).
 * 이름+세대 → "안녕하세요, 최주민님 (401동 201호)" · 이름만 → "안녕하세요, 최주민님" ·
 * 이름 없음 → "안녕하세요".
 */
export function greeting(name: string | null, unit: string | null): string {
  if (!name) return "안녕하세요";
  return unit ? `안녕하세요, ${name}님 (${unit})` : `안녕하세요, ${name}님`;
}
