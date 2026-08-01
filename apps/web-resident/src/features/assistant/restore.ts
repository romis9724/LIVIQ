/**
 * 서버 대화 복원 매핑 (ADR-0027 결정 1).
 *
 * 탭 저장소가 비었을 때(새 탭·브라우저 재시작) `GET /assistant/conversations/latest` 응답을
 * 화면 메시지로 옮긴다. **텍스트 위주** 복원이다 — 구조화 표·CTA·진행 단계는 서버가 갖고 있지
 * 않고(SSE 일회성), 과거 답변의 행동 버튼을 되살릴 가치도 낮다. 렌더 계약을 지키려고
 * `citations`·`steps` 는 빈 배열로 채운다.
 */

import type { DoneResult } from "./api";
import type { ChatMessage } from "./useAssistantStream";

export interface RestoredThread {
  conversationId: string | null;
  messages: ChatMessage[];
}

const EMPTY_RESTORED: RestoredThread = { conversationId: null, messages: [] };

/** 복원 메시지가 갖는 진행 단계 — 이미 끝난 답변이라 마지막 단계로 고정. */
const DONE_STAGE = "verifying" as const;

/** 서버 상태 → 화면 분기 계약. `handed_off` 는 화면에서 폴백(담당자 연결)과 같은 자리다. */
function toDoneStatus(status: unknown): DoneResult["status"] {
  if (status === "answered" || status === "clarify") return status;
  return "fallback";
}

function toMessage(value: unknown, conversationId: string): ChatMessage | null {
  if (typeof value !== "object" || value === null) return null;
  const { id, role, content, status } = value as Record<string, unknown>;
  if (typeof id !== "string" || typeof content !== "string" || content === "") return null;
  if (role === "user") return { id, role: "user", text: content };
  if (role !== "assistant") return null;
  return {
    id,
    role: "ai",
    status: "done",
    stage: DONE_STAGE,
    tool: null,
    text: content,
    citations: [],
    steps: [],
    result: {
      messageId: id,
      conversationId,
      status: toDoneStatus(status),
      confidence: 0,
      needsReview: false,
      fallbackReason: null,
      answer: content,
      // 도구 경로·제안은 저장하지 않는다 → CTA·후속 칩 없이 본문만 복원된다.
      toolPath: [],
      suggestions: [],
    },
  };
}

/**
 * 서버 응답 → 복원 대화. 와이어에서 온 값이라 신뢰하지 않는다 — 형태가 어긋나면 빈 대화다
 * (session-store `parseThread` 와 같은 원칙: 복원 실패가 화면을 막으면 안 된다).
 */
export function parseLatestThread(raw: unknown): RestoredThread {
  if (typeof raw !== "object" || raw === null) return EMPTY_RESTORED;
  const { conversation_id: conversationId, messages } = raw as Record<string, unknown>;
  // 대화 id 가 없으면 이어서 물어볼 수단이 없다 — 메시지만 되살리지 않는다.
  if (typeof conversationId !== "string" || !Array.isArray(messages)) return EMPTY_RESTORED;
  const restored = messages
    .map((m) => toMessage(m, conversationId))
    .filter((m): m is ChatMessage => m !== null);
  return restored.length === 0 ? EMPTY_RESTORED : { conversationId, messages: restored };
}
