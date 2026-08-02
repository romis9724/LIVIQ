// 시설 AI 도우미 — POST /admin/facilities/assistant SSE 스트림 클라이언트 (docs/09 §1.1).
// 파서·이벤트 타입은 @liviq/ui 공용(ADR-0028 결정 4 — 복붙본 폐기). 여기 남는 것은 엔드포인트뿐이다.

import { streamAssistant, type AssistantEvent } from "@liviq/ui";
import { API_BASE_URL, apiFetch } from "@/lib/api";

export interface AskOptions {
  conversationId?: string | null;
  signal?: AbortSignal;
}

/** POST /admin/facilities/assistant → SSE 이벤트 스트림. */
export function streamFacilityAssistant(
  question: string,
  opts: AskOptions = {},
): AsyncGenerator<AssistantEvent> {
  return streamAssistant(
    `${API_BASE_URL}/admin/facilities/assistant`,
    { question, conversation_id: opts.conversationId ?? null },
    { apiFetch, signal: opts.signal },
  );
}
