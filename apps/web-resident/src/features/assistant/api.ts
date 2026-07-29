// AI 비서 — api SSE 스트림 클라이언트 (docs/09 §1.1 이벤트 계약).
// 브라우저 EventSource는 GET만 지원 → POST SSE는 fetch + ReadableStream으로 직접 파싱.

import { API_BASE_URL, DEV_HEADERS, apiFetch } from "@/lib/dev-context";

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
  /**
   * 서버가 확정한 답변 본문. 있으면 누적 토큰 텍스트 대신 **이 값을 렌더한다.**
   * 인용 누락 재요청(H15-2 R21) 때 1차 답변은 이미 token으로 흘렀고 재요청 결과는
   * 스트리밍하지 않으므로, 이 값이 최종본이다. 없으면 누적 텍스트가 그대로 정본.
   */
  answer: string | null;
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
            answer: d.answer ?? null,
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
  const response = await apiFetch(`${API_BASE_URL}/assistant/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...DEV_HEADERS,
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
