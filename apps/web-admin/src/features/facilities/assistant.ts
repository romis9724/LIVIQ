// 시설 AI 도우미 — POST /admin/facilities/assistant SSE 스트림 클라이언트 (docs/09 §1.1).
// web-resident assistant/api.ts 파서 패턴 재사용(로컬 타입 정의) — POST SSE는 fetch로 직접 파싱.

import { API_BASE_URL, DEV_HEADERS } from "@/lib/api";

export type Stage = "searching" | "generating" | "verifying";

export interface AssistantCitation {
  ref: number;
  documentId: string | null; // 도구 결과 인용은 null(H2-5 완화) — title만 표기.
  documentTitle: string;
  quote: string;
  page: number | null;
  clause: string | null;
}

export interface DoneResult {
  messageId: string | null;
  conversationId: string;
  status: "answered" | "fallback";
  confidence: number;
  needsReview: boolean;
  fallbackReason: string | null;
  toolPath: string[];
}

export type AssistantEvent =
  | { type: "status"; stage: Stage }
  | { type: "token"; text: string }
  | { type: "citation"; citation: AssistantCitation }
  | { type: "done"; result: DoneResult };

interface SseFrame {
  event: string;
  data: string;
}

/**
 * 버퍼에서 완결된 SSE 프레임(빈 줄 구분)만 잘라낸다. 반환: [완결 프레임, 남은 버퍼].
 * 개행은 LF로 정규화(sse-starlette CRLF 대응).
 */
export function parseSseBuffer(buffer: string): [SseFrame[], string] {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const frames: SseFrame[] = [];
  const parts = normalized.split("\n\n");
  const rest = parts.pop() ?? "";
  for (const block of parts) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length > 0) frames.push({ event, data: dataLines.join("\n") });
  }
  return [frames, rest];
}

/** SSE 프레임 → 도메인 이벤트. 알 수 없는 이벤트·파싱 실패는 null(무시). */
export function toEvent(frame: SseFrame): AssistantEvent | null {
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
          citation: {
            ref: d.ref,
            documentId: d.document_id ?? null,
            documentTitle: d.document_title,
            quote: d.quote,
            page: d.page ?? null,
            clause: d.clause ?? null,
          },
        };
      case "done":
        return {
          type: "done",
          result: {
            messageId: d.message_id ?? null,
            conversationId: d.conversation_id,
            status: d.status,
            confidence: d.confidence,
            needsReview: d.needs_review,
            fallbackReason: d.fallback_reason ?? null,
            toolPath: Array.isArray(d.tool_path) ? d.tool_path : [],
          },
        };
      default:
        return null;
    }
  } catch {
    return null;
  }
}

export interface AskOptions {
  conversationId?: string | null;
  signal?: AbortSignal;
}

/** POST /admin/facilities/assistant → SSE 이벤트 스트림. */
export async function* streamFacilityAssistant(
  question: string,
  opts: AskOptions = {},
): AsyncGenerator<AssistantEvent> {
  const response = await fetch(`${API_BASE_URL}/admin/facilities/assistant`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...DEV_HEADERS },
    body: JSON.stringify({ question, conversation_id: opts.conversationId ?? null }),
    signal: opts.signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`시설 도우미 요청 실패: ${response.status}`);
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
      const event = toEvent(frame);
      if (event) yield event;
    }
  }
}
