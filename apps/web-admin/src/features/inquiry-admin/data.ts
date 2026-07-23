import type { Inquiry, InquiryEvent, InquiryEventType, InquiryStatus, Priority } from "@/lib/api";

// 상태 배지 — 색만으로 전달하지 않고 라벨 병기(WCAG 2.2 AA). class 는 ia-status--<suffix>.
// 상태 전이는 액션(ack·complete·재개)이 결정 — 수동 전이 없음(ADR-0018).
export const STATUS_META: Record<InquiryStatus, { label: string; suffix: string }> = {
  received: { label: "미배정", suffix: "received" },
  assigned: { label: "배정됨", suffix: "assigned" },
  in_progress: { label: "처리중", suffix: "progress" },
  reopened: { label: "재확인", suffix: "progress" },
  done: { label: "완료", suffix: "done" },
};

// 우선순위 배지 — 수동 priority(3종) → 아이콘·라벨·class 접미사.
export const PRIORITY_META: Record<Priority, { icon: string; label: string; suffix: string }> = {
  urgent: { icon: "▲", label: "긴급", suffix: "high" },
  normal: { icon: "■", label: "보통", suffix: "mid" },
  low: { icon: "▼", label: "낮음", suffix: "low" },
};

// 우선순위 select 선택지 — null="지정안함". 값 매핑은 화면에서 문자열↔null 로 환산.
export const PRIORITY_OPTIONS: readonly { value: Priority | ""; label: string }[] = [
  { value: "", label: "지정안함" },
  { value: "urgent", label: "긴급" },
  { value: "normal", label: "보통" },
  { value: "low", label: "낮음" },
];

export type FilterId = "all" | InquiryStatus;
export const FILTERS: readonly { id: FilterId; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "received", label: "미배정" },
  { id: "assigned", label: "배정됨" },
  { id: "in_progress", label: "처리중" },
  { id: "reopened", label: "재확인" },
  { id: "done", label: "완료" },
];

/** 필터별 개수 집계 — all 은 전체 기준. */
export function countByStatus(inquiries: readonly Inquiry[]): Record<FilterId, number> {
  const counts: Record<FilterId, number> = {
    all: inquiries.length,
    received: 0,
    assigned: 0,
    in_progress: 0,
    reopened: 0,
    done: 0,
  };
  for (const inquiry of inquiries) counts[inquiry.status] += 1;
  return counts;
}

/** ISO → "MM/DD". */
export function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${mm}/${dd}`;
}

// ── 처리 내역(inquiry_events) 표시 헬퍼 ──────────────────────────────────────

const EVENT_LABEL: Record<InquiryEventType, string> = {
  created: "민원 접수됨",
  ai_classified: "AI 분류",
  assigned: "담당자 배정",
  status_changed: "상태 변경",
  comment: "코멘트",
};

export function eventLabel(type: InquiryEventType): string {
  return EVENT_LABEL[type];
}

// status_changed payload → "접수됨 → 처리중". 알 수 없는 코드는 원문 유지.
export function formatStatusChange(payload: InquiryEvent["payload"]): string | null {
  if (!payload) return null;
  const from = typeof payload.from === "string" ? payload.from : null;
  const to = typeof payload.to === "string" ? payload.to : null;
  if (!to) return null;
  const label = (s: string): string => STATUS_META[s as InquiryStatus]?.label ?? s;
  return from ? `${label(from)} → ${label(to)}` : label(to);
}

// comment 이벤트 payload → 발신 갈래("reply"=담당자 답변 · "feedback"=입주민 피드백).
export function commentKind(payload: InquiryEvent["payload"]): "reply" | "feedback" | null {
  if (!payload) return null;
  const kind = payload.kind;
  return kind === "reply" || kind === "feedback" ? kind : null;
}

// comment 이벤트 payload → 본문. 문자열이 아니면 "".
export function commentBody(payload: InquiryEvent["payload"]): string {
  if (!payload) return "";
  return typeof payload.body === "string" ? payload.body : "";
}

// 서버가 created_at 오름차순 정렬하지만 방어적으로 다시 정렬.
export function sortEvents(events: readonly InquiryEvent[]): InquiryEvent[] {
  return [...events].sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

/** 완료 게이트 — reply(담당자 답변) 이벤트가 1건이라도 있는지. */
export function hasReply(events: readonly InquiryEvent[]): boolean {
  return events.some((ev) => ev.type === "comment" && commentKind(ev.payload) === "reply");
}
