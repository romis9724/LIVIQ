// AI 비서 우측 민원현황 패널 — 표시 로직(순수 함수, 테스트 대상).
// 집계·라벨은 features/inquiry-admin/data.ts 를 그대로 쓴다(단일 정의 — 여기서 다시 만들지 않는다).

import type { StatusKind } from "@liviq/ui";
import type { Inquiry, InquiryStatus } from "@/lib/api";
import { STATUS_META, type FilterId } from "@/features/inquiry-admin/data";

/** 패널에 세울 상태 줄 순서. `reopened`(재확인)는 0건이면 줄을 만들지 않는다. */
const ROW_ORDER: readonly InquiryStatus[] = [
  "received",
  "assigned",
  "in_progress",
  "reopened",
  "done",
];

/** 값 색으로 경고할 상태 — 미배정·처리중(관리소장이 바로 손대야 하는 것). */
const ALERT_STATUSES: ReadonlySet<InquiryStatus> = new Set(["received", "in_progress"]);

export interface StatusRow {
  status: InquiryStatus;
  label: string;
  count: number;
  /** 0이 아닐 때만 강조(docs/05 §5A — 강조는 값 색만). */
  alert: boolean;
}

/** 상태별 카운트 → 표시 줄. reopened 는 존재할 때만 낀다. */
export function statusRows(counts: Record<FilterId, number>): StatusRow[] {
  return ROW_ORDER.filter((status) => status !== "reopened" || counts.reopened > 0).map(
    (status) => ({
      status,
      label: STATUS_META[status].label,
      count: counts[status],
      alert: ALERT_STATUSES.has(status) && counts[status] > 0,
    }),
  );
}

/** 최근 민원 N건 — createdAt 내림차순(서버 정렬을 믿지 않는다). 원본은 건드리지 않는다. */
export function recentInquiries(inquiries: readonly Inquiry[], limit: number): Inquiry[] {
  return [...inquiries].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, limit);
}

const DAY_MS = 86_400_000;
/** 이 일수를 넘기면 상대 표기 대신 날짜(MM/DD)로 — "37일 전"은 읽어도 감이 안 온다. */
const RELATIVE_LIMIT_DAYS = 7;

/** 자정 기준 날짜 수(로컬) — 시각 차이가 아니라 "며칠 전"을 세기 위한 것. */
function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** ISO → "오늘"·"어제"·"N일 전"·"MM/DD". 파싱 실패는 "—"(지어내지 않음). */
export function relativeDay(iso: string, now: Date): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const days = Math.round((startOfDay(now) - startOfDay(date)) / DAY_MS);
  if (days <= 0) return "오늘";
  if (days === 1) return "어제";
  if (days <= RELATIVE_LIMIT_DAYS) return `${days}일 전`;
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${mm}/${dd}`;
}

// StatusPill 은 4종뿐이라(received·progress·done·fault) 민원 5상태를 접어 넣는다.
// 라벨은 STATUS_META 원문을 그대로 넘기므로 글자로는 5상태가 구분된다.
const PILL_KIND: Record<InquiryStatus, StatusKind> = {
  received: "received",
  assigned: "received",
  in_progress: "progress",
  reopened: "progress",
  done: "done",
};

export function pillKind(status: InquiryStatus): StatusKind {
  return PILL_KIND[status];
}
