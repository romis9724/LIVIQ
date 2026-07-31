// AI 비서 — api SSE 스트림 클라이언트 (docs/09 §1.1 이벤트 계약).
// 브라우저 EventSource는 GET만 지원 → POST SSE는 fetch + ReadableStream으로 직접 파싱.

import { API_BASE_URL, DEV_HEADERS, apiFetch } from "@/lib/dev-context";

export type Stage = "searching" | "generating" | "verifying";

export interface Citation {
  ref: number;
  /** 문서 인용은 문서 id, **도구 결과 카드는 null**(제목·quote 로 식별 — 주차 CTA 가 쓴다). */
  documentId: string | null;
  documentTitle: string;
  quote: string;
  page: number | null;
  clause: string | null;
  /**
   * 도구 결과의 구조화 페이로드(ADR-0025 §6). 문서 인용은 항상 null.
   * 서버가 확정한 값이지만 와이어에서 온 JSON 이라 여기서는 좁히지 않는다 —
   * `structured.ts` 의 `toStructured` 가 kind 별로 검사해 좁힌다(모르는 kind 는 무시).
   */
  data: unknown;
}

export interface DoneResult {
  messageId: string | null;
  conversationId: string;
  /** `clarify` = 되묻기(ADR-0025 §4) — 답변이 아니라 **질문**이라 폴백으로 취급하지 않는다. */
  status: "answered" | "fallback" | "clarify";
  confidence: number;
  needsReview: boolean;
  fallbackReason: string | null;
  /**
   * 서버가 확정한 답변 본문. 있으면 누적 토큰 텍스트 대신 **이 값을 렌더한다.**
   * 스트리밍 토큰은 마스킹된 원문이라 PII 자리표시자가 보일 수 있고, 이 값은 unmask 후의
   * 최종본이다. 없으면 누적 텍스트가 그대로 정본.
   */
  answer: string | null;
  /**
   * 이번 답변에서 호출된 도구 이름 순서. 프론트는 민원성 질의 판정에만 쓴다
   * (`search_similar_inquiries` 포함 → 접수 CTA 렌더, ADR-0024).
   */
  toolPath: string[];
  /**
   * 맥락 기반 다음 행동 제안 최대 3개(ADR-0025 §7 — 코드 규칙 생성, LLM 미개입).
   * 비어 있으면 칩을 렌더하지 않는다.
   */
  suggestions: string[];
}

export type AssistantEvent =
  /** `tool` = 지금 실행 중인 도구 이름. 도구 없는 단계(첫 searching·generating·verifying)는 null. */
  | { type: "status"; stage: Stage; tool: string | null }
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

/** SSE 프레임 → 앱 이벤트. 알 수 없는 event 명·깨진 JSON 은 null(무시). */
export function toEvent(frame: SseFrame): AssistantEvent | null {
  try {
    const d = JSON.parse(frame.data);
    switch (frame.event) {
      case "status":
        return { type: "status", stage: d.stage, tool: d.tool ?? null };
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
            data: d.data ?? null,
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
            toolPath: d.tool_path ?? [],
            suggestions: d.suggestions ?? [],
          },
        };
      default:
        return null;
    }
  } catch {
    return null;
  }
}

/** AI 말풍선이 취할 수 있는 표시 형태. 렌더 분기의 단일 출처(컴포넌트 밖에서 테스트 가능). */
export type AnswerKind = "streaming" | "answered" | "clarify" | "fallback";

/**
 * AI 메시지를 어떤 형태로 그릴지 판정한다.
 * 되묻기를 따로 빼는 이유: 기존 분기는 `answered` 가 아니면 전부 폴백 UI(담당자 연결)로
 * 떨어뜨리는데, 되묻기는 실패가 아니라 사용자에게 되던지는 질문이다.
 */
export function answerKind(message: {
  status: "streaming" | "done";
  error?: boolean;
  result?: Pick<DoneResult, "status">;
}): AnswerKind {
  if (message.status === "streaming") return "streaming";
  if (message.error) return "fallback";
  if (message.result?.status === "clarify") return "clarify";
  return message.result?.status === "answered" ? "answered" : "fallback";
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
