// 관리비 — apps/api HTTP·SSE 클라이언트 (docs/01 §13, 규칙 5 — 표시 전용).
// 조회는 서버 확정 데이터 그대로, AI 설명은 SSE 스트림. SSE 프레임 파싱은 assistant 재사용.

import { API_BASE_URL, DEV_HEADERS } from "@/lib/dev-context";
import { parseSseBuffer } from "../assistant/api";

export interface FeeData {
  period: string;
  breakdown: Record<string, number> | null;
  total: number | null;
  prevTotal: number | null;
}

/** 상태코드를 담은 에러 — 화면 분기용. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function ensureOk(response: Response): Promise<void> {
  if (response.ok) return;
  let detail = `요청 실패 (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // 본문 파싱 실패는 무시 — 상태코드 기반 기본 메시지 유지
  }
  throw new ApiError(response.status, detail);
}

/** 본인 세대 해당 월 관리비. 데이터 없는 월은 breakdown·total null. */
export async function getFees(period: string): Promise<FeeData> {
  const response = await fetch(
    `${API_BASE_URL}/fees?period=${encodeURIComponent(period)}`,
    { headers: DEV_HEADERS },
  );
  await ensureOk(response);
  const body = await response.json();
  return {
    period: body.period,
    breakdown: body.breakdown ?? null,
    total: body.total ?? null,
    prevTotal: body.prev_total ?? null,
  };
}

/** 전월 대비 차액(원)·방향. 계산 아님 — 서버 total·prevTotal의 표시용 차이. */
export interface FeeDelta {
  amount: number; // 양수=증가, 음수=감소
  direction: "up" | "down" | "flat";
}

export function feeDelta(total: number | null, prevTotal: number | null): FeeDelta | null {
  if (total == null || prevTotal == null) return null;
  const amount = total - prevTotal;
  const direction = amount > 0 ? "up" : amount < 0 ? "down" : "flat";
  return { amount, direction };
}

/** 원 단위 금액 표기. 예: 238400 → "238,400원". */
export function formatWon(n: number): string {
  return `${n.toLocaleString("ko-KR")}원`;
}

// ── AI 설명 SSE (POST /fees/explain) ─────────────────────────────────────────

export type ExplainStage = "searching" | "generating" | "verifying";
export type ExplainStatus = "answered" | "fallback";

export interface FeeCitation {
  documentTitle: string;
  quote: string;
}

export interface FeeExplainDone {
  status: ExplainStatus;
  confidence: number;
  needsReview: boolean;
  fallbackReason: string | null;
}

export type FeeExplainEvent =
  | { type: "status"; stage: ExplainStage }
  | { type: "token"; text: string }
  | { type: "citation"; citation: FeeCitation }
  | { type: "done"; result: FeeExplainDone };

/** SSE 프레임 → 관리비 설명 이벤트. 파싱 실패·미지원 이벤트는 null. */
export function toFeeEvent(frame: { event: string; data: string }): FeeExplainEvent | null {
  try {
    const d = JSON.parse(frame.data);
    switch (frame.event) {
      case "status":
        return { type: "status", stage: d.stage };
      case "token":
        return { type: "token", text: d.text };
      case "citation":
        return {
          type: "citation",
          citation: { documentTitle: d.document_title, quote: d.quote },
        };
      case "done":
        return {
          type: "done",
          result: {
            status: d.status,
            confidence: d.confidence,
            needsReview: d.needs_review,
            fallbackReason: d.fallback_reason ?? null,
          },
        };
      default:
        return null;
    }
  } catch {
    return null;
  }
}

/** POST /fees/explain → SSE 이벤트 스트림. 404=해당 월 데이터 없음. */
export async function* streamFeeExplain(
  period: string,
  signal?: AbortSignal,
): AsyncGenerator<FeeExplainEvent> {
  const response = await fetch(`${API_BASE_URL}/fees/explain`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ period }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, `관리비 설명 요청 실패 (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const [frames, rest] = parseSseBuffer(buffer);
    buffer = rest;
    for (const frame of frames) {
      const event = toFeeEvent(frame);
      if (event) yield event;
    }
  }
}
