// AI 비서 우측 민원현황 패널 — 표시 로직(순수 함수, 테스트 대상).
// 집계·라벨은 features/inquiry-admin/data.ts 를 그대로 쓴다(단일 정의 — 여기서 다시 만들지 않는다).

import type { StatusKind } from "@liviq/ui";
import { ApiError, type Inquiry, type InquiryEvent, type InquiryStatus } from "@/lib/api";
import {
  STATUS_META,
  commentBody,
  commentKind,
  eventLabel,
  formatStatusChange,
  shortDate,
  sortEvents,
  type FilterId,
} from "@/features/inquiry-admin/data";

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

/** 조회 실패 문구 — 패널·드릴다운 공용. 알 수 없는 예외도 화면에 문장을 남긴다. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

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

/** ISO 기준 now 까지 며칠 지났는지(자정 기준). 파싱 실패는 null — 지어내지 않는다. */
export function elapsedDays(iso: string, now: Date): number | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return Math.max(0, Math.round((startOfDay(now) - startOfDay(date)) / DAY_MS));
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

// ── 상태 카드 드릴다운(H20-13) ──────────────────────────────────────────────

/** 이 일수를 넘긴 미완료 건은 재촉 표식 — 값 색으로만 강조(docs/05 §5A). */
const OVERDUE_DAYS = 7;

export interface DrilldownRow {
  inquiry: Inquiry;
  /** 표시 기준 — 미완료는 접수일, 완료는 완료일. */
  dateKind: "received" | "completed";
  /** MM/DD. 파싱 실패는 "—". */
  dateLabel: string;
  /** 미완료만 접수 후 경과일(재촉 목적). 완료 건은 null. */
  elapsedDays: number | null;
  overdue: boolean;
}

/** 완료 시각 — 전용 컬럼이 없다. done 이후에는 서버가 변경을 잠그므로(_guard_not_done)
 *  updatedAt 이 사실상 완료 시각이다. 정확한 시각이 필요하면 타임라인(inquiry_events)을 본다. */
function completedAt(inquiry: Inquiry): string {
  return inquiry.updatedAt;
}

/**
 * 상태 카드 클릭 → 그 상태의 민원 줄. 미완료는 접수 오래된 순(재촉), 완료는 완료 최신순.
 * 패널이 이미 전량을 들고 있으므로 서버 재조회 없이 걸러 쓴다. 원본은 건드리지 않는다.
 */
export function drilldownRows(
  inquiries: readonly Inquiry[],
  status: InquiryStatus,
  now: Date,
): DrilldownRow[] {
  const done = status === "done";
  const matched = inquiries.filter((it) => it.status === status);
  const sorted = done
    ? [...matched].sort((a, b) => completedAt(b).localeCompare(completedAt(a)))
    : [...matched].sort((a, b) => a.createdAt.localeCompare(b.createdAt));

  return sorted.map((inquiry) => {
    const iso = done ? completedAt(inquiry) : inquiry.createdAt;
    const days = done ? null : elapsedDays(inquiry.createdAt, now);
    return {
      inquiry,
      dateKind: done ? "completed" : "received",
      dateLabel: shortDate(iso),
      elapsedDays: days,
      overdue: days !== null && days >= OVERDUE_DAYS,
    };
  });
}

/** 한 줄 발췌 — 줄바꿈·연속 공백을 접고 상한을 넘기면 말줄임. */
export function excerpt(text: string, limit: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat;
}

/** 처리 내역 한 줄의 본문 발췌 상한 — 패널은 좁으므로 짧게. */
const HISTORY_BODY_LIMIT = 60;

export interface HistoryLine {
  id: string;
  /** MM/DD */
  date: string;
  text: string;
}

/** 이벤트 한 건 → 한 줄 문구. 라벨 + (상태 전이 | 코멘트 발췌). */
function historyText(event: InquiryEvent): string {
  const label = eventLabel(event.type);
  if (event.type === "comment") {
    const kind = commentKind(event.payload);
    const who = kind === "reply" ? "담당자 답변" : kind === "feedback" ? "입주민 피드백" : label;
    const body = excerpt(commentBody(event.payload), HISTORY_BODY_LIMIT);
    return body ? `${who} · ${body}` : who;
  }
  const change = event.type === "status_changed" ? formatStatusChange(event.payload) : null;
  return change ? `${label} · ${change}` : label;
}

/** 처리 내역(inquiry_events) → 시간순 압축 목록. 요약은 코드가 만든다(LLM 호출 없음 — 규칙 7). */
export function historyLines(events: readonly InquiryEvent[]): HistoryLine[] {
  return sortEvents(events).map((event) => ({
    id: event.id,
    date: shortDate(event.createdAt),
    text: historyText(event),
  }));
}
