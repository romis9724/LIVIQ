/**
 * AI 비서 대화의 탭 수명 보관 (H17 UI 정리).
 *
 * 주차맵("주차위치 보기") 같은 다른 화면으로 이동하면 컴포넌트가 언마운트돼 대화가 통째로
 * 사라졌다. 뒤로가기로 돌아왔을 때 직전 대화가 그대로 보이도록 `sessionStorage` 에 저장한다.
 * **탭 단위**가 맞는 수명이다 — 새 탭·브라우저 재시작이면 새 대화로 시작하는 게 자연스럽고,
 * 대화에는 세대·차량 같은 개인정보가 섞일 수 있어 영구 보관(localStorage)은 피한다.
 */

import type { ChatMessage } from "./useAssistantStream";

/** 저장 키 — 스키마가 바뀌면 뒤 버전을 올려 옛 값을 자연 폐기한다.
 *  v2: AI 메시지에 `steps`(진행 단계) 추가 — H18-3. */
export const THREAD_STORAGE_KEY = "liviq.assistant.thread.v2";

export interface StoredThread {
  messages: ChatMessage[];
  /** 서버 대화 id — 복원 후 이어지는 질문이 같은 대화로 붙도록 함께 저장. */
  conversationId: string | null;
}

export const EMPTY_THREAD: StoredThread = { messages: [], conversationId: null };

/** 저장 상한 — 긴 대화가 탭 저장소(≈5MB)를 채우지 않도록 최근 것만 남긴다. */
const MAX_STORED_MESSAGES = 40;

function isChatMessage(value: unknown): value is ChatMessage {
  if (typeof value !== "object" || value === null) return false;
  const m = value as Record<string, unknown>;
  if (typeof m.id !== "string" || typeof m.text !== "string") return false;
  if (m.role === "user") return true;
  // ai 메시지는 렌더가 citations·steps 배열을 반드시 훑는다 — 없으면 복원 즉시 터진다.
  return m.role === "ai" && Array.isArray(m.citations) && Array.isArray(m.steps);
}

/**
 * 저장 대상만 골라낸다. 스트리밍 중인 메시지는 제외 — 저장 시점의 반쪽짜리 텍스트가
 * 복원되면 영원히 커서만 깜빡이는 유령 말풍선이 된다.
 */
export function persistableMessages(messages: readonly ChatMessage[]): ChatMessage[] {
  return messages
    .filter((m) => m.role === "user" || m.status === "done")
    .slice(-MAX_STORED_MESSAGES);
}

/**
 * 저장본 파싱. 사용자가 손댈 수 있는 저장소라 신뢰하지 않는다 —
 * 깨진 JSON·다른 스키마는 조용히 빈 대화로 떨어진다(복원 실패가 화면을 막으면 안 된다).
 */
export function parseThread(raw: string | null): StoredThread {
  if (!raw) return EMPTY_THREAD;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return EMPTY_THREAD;
    const { messages, conversationId } = parsed as Record<string, unknown>;
    if (!Array.isArray(messages)) return EMPTY_THREAD;
    return {
      messages: messages.filter(isChatMessage),
      conversationId: typeof conversationId === "string" ? conversationId : null,
    };
  } catch {
    return EMPTY_THREAD;
  }
}

/** 복원 — SSR·프라이빗 모드 등 sessionStorage 가 없거나 던지는 환경도 빈 대화로 처리. */
export function readThread(): StoredThread {
  try {
    return parseThread(window.sessionStorage.getItem(THREAD_STORAGE_KEY));
  } catch {
    return EMPTY_THREAD;
  }
}

/** 저장 — 용량 초과(QuotaExceeded) 등으로 실패해도 대화 자체는 계속돼야 한다. */
export function writeThread(thread: StoredThread): void {
  try {
    window.sessionStorage.setItem(THREAD_STORAGE_KEY, JSON.stringify(thread));
  } catch {
    // 보관은 편의 기능일 뿐 — 실패해도 화면 동작에는 영향 없다.
  }
}
