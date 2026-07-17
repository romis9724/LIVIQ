import type { AiPriority, Inquiry, InquiryStatus } from "@/lib/api";

// 상태 머신 전진 순서 — 서버가 역행을 검증하므로 UI 는 전진 옵션만 노출.
export const STATUS_ORDER: readonly InquiryStatus[] = [
  "received",
  "assigned",
  "in_progress",
  "done",
];

// 상태 배지 — 색만으로 전달하지 않고 라벨 병기(WCAG 2.2 AA). class 는 ia-status--<suffix>.
export const STATUS_META: Record<InquiryStatus, { label: string; suffix: string }> = {
  received: { label: "접수됨", suffix: "received" },
  assigned: { label: "배정됨", suffix: "assigned" },
  in_progress: { label: "처리중", suffix: "progress" },
  done: { label: "완료", suffix: "done" },
};

// 우선순위 배지 — ai_priority(3종) → 아이콘·라벨·class 접미사.
export const PRIORITY_META: Record<AiPriority, { icon: string; label: string; suffix: string }> = {
  urgent: { icon: "▲", label: "긴급", suffix: "high" },
  normal: { icon: "■", label: "보통", suffix: "mid" },
  low: { icon: "▼", label: "낮음", suffix: "low" },
};

export type FilterId = "all" | InquiryStatus;
export const FILTERS: readonly { id: FilterId; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "received", label: "접수됨" },
  { id: "assigned", label: "배정됨" },
  { id: "in_progress", label: "처리중" },
  { id: "done", label: "완료" },
];

/** 필터별 개수 집계 — all 은 전체 기준. */
export function countByStatus(inquiries: readonly Inquiry[]): Record<FilterId, number> {
  const counts: Record<FilterId, number> = {
    all: inquiries.length,
    received: 0,
    assigned: 0,
    in_progress: 0,
    done: 0,
  };
  for (const inquiry of inquiries) counts[inquiry.status] += 1;
  return counts;
}

/** 현 상태에서 전진 가능한 다음 상태들(전진만 — 역행은 서버 권한 검증). */
export function nextStatuses(current: InquiryStatus): InquiryStatus[] {
  return STATUS_ORDER.slice(STATUS_ORDER.indexOf(current) + 1);
}

/** ISO → "MM/DD". */
export function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${mm}/${dd}`;
}
