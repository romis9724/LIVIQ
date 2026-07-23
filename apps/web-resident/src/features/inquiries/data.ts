import type { StatusKind } from "@liviq/ui";

import type { InquiryEvent, InquiryEventType, InquiryStatus, Priority } from "@/lib/api";

export const STATUS_LABEL: Record<InquiryStatus, string> = {
  received: "접수됨",
  assigned: "배정됨",
  in_progress: "처리중",
  done: "완료",
};

export const PRIORITY_LABEL: Record<Priority, string> = {
  urgent: "긴급",
  normal: "보통",
  low: "낮음",
};

// StatusPill 색상(3종) 매핑 — 실제 상태(4종)를 시각적으로 접힌다.
const STATUS_PILL_KIND: Record<InquiryStatus, StatusKind> = {
  received: "received",
  assigned: "progress",
  in_progress: "progress",
  done: "done",
};

export function statusPill(status: InquiryStatus): { status: StatusKind; label: string } {
  return { status: STATUS_PILL_KIND[status], label: STATUS_LABEL[status] };
}

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
  const label = (s: string): string => STATUS_LABEL[s as InquiryStatus] ?? s;
  return from ? `${label(from)} → ${label(to)}` : label(to);
}

// comment 이벤트 payload → 발신 갈래("reply"=담당자 답변 · "feedback"=입주민 피드백).
// 알 수 없는 kind 는 null.
export function commentKind(
  payload: InquiryEvent["payload"],
): "reply" | "feedback" | null {
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
