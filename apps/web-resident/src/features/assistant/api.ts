// AI 비서 — api SSE 스트림 클라이언트 (docs/09 §1.1 이벤트 계약).
// 브라우저 EventSource는 GET만 지원 → POST SSE는 fetch + ReadableStream으로 직접 파싱.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// local dev 전용 컨텍스트(정식 세션 인증 도입 전). 실제 시드된 tenant/user와 일치해야 함.
const DEV_TENANT_ID =
  process.env.NEXT_PUBLIC_DEV_TENANT_ID ?? "11111111-1111-1111-1111-111111111111";
const DEV_USER_ID =
  process.env.NEXT_PUBLIC_DEV_USER_ID ?? "22222222-2222-2222-2222-222222222222";

export type Stage = "searching" | "generating" | "verifying";

export interface Citation {
  ref: number;
  documentId: string;
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
}

export type AssistantEvent =
  | { type: "status"; stage: Stage }
  | { type: "token"; text: string }
  | { type: "citation"; citation: Citation }
  | { type: "done"; result: DoneResult };

interface SseFrame {
  event: string;
  data: string;
}

/**
 * 버퍼 문자열에서 완결된 SSE 프레임(빈 줄 `\n\n` 구분)만 잘라낸다.
 * 반환: [완결 프레임들, 남은 미완결 버퍼]. reader 청크가 프레임 경계에서
 * 안 잘리는 문제를 버퍼링으로 처리한다.
 */
export function parseSseBuffer(buffer: string): [SseFrame[], string] {
  // 개행을 LF로 정규화(sse-starlette 등은 CRLF 사용) 후 빈 줄로 프레임 분리.
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

function toEvent(frame: SseFrame): AssistantEvent | null {
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
            documentId: d.document_id,
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

/** POST /assistant/ask → SSE 이벤트 스트림. */
export async function* streamAsk(
  question: string,
  opts: AskOptions = {},
): AsyncGenerator<AssistantEvent> {
  const response = await fetch(`${API_BASE_URL}/assistant/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Dev-Tenant-Id": DEV_TENANT_ID,
      "X-Dev-User-Id": DEV_USER_ID,
    },
    body: JSON.stringify({
      question,
      conversation_id: opts.conversationId ?? null,
    }),
    signal: opts.signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`assistant 요청 실패: ${response.status}`);
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
