"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type AssistantCitation,
  type AssistantDoneResult,
  type AssistantStage,
  type FetchLike,
  streamAssistant,
} from "./assistant-events";
import { appendProgress } from "./assistant-progress";
import type { RestoredThread } from "./assistant-restore";
import {
  clearThread,
  persistableMessages,
  readThread,
  writeThread,
} from "./assistant-session-store";

export interface AiMessage {
  id: string;
  role: "ai";
  status: "streaming" | "done";
  stage: AssistantStage;
  /** 지금 실행 중인 도구 — 스트리밍 중 한 줄 힌트에만 쓴다(끝나면 steps 가 기록). */
  tool: string | null;
  text: string;
  citations: AssistantCitation[];
  /** 지나온 진행 단계 라벨. 답변 후 접이식 "답변 과정"으로 되짚는다(H18-3 ①). */
  steps: string[];
  result?: AssistantDoneResult;
  error?: boolean;
}

export interface UserMessage {
  id: string;
  role: "user";
  text: string;
}

export type ChatMessage = AiMessage | UserMessage;

export interface AssistantStreamOptions {
  /** 질문 POST 대상. 앱마다 다르다(입주민 `/assistant/ask` 등). */
  askUrl: string;
  /** 앱의 인증 fetch 래퍼 — ui 는 세션·dev 헤더 정책을 모른다. */
  apiFetch: FetchLike;
  /** 탭 저장소 키. 앱끼리 대화가 섞이지 않도록 앱이 정한다. */
  storageKey: string;
  /**
   * 서버 최근 대화 복원(2차 폴백, ADR-0027 결정 1). **주지 않으면 서버 복원을 건너뛴다** —
   * 복원 엔드포인트가 없는 화면(관리자 홈)이 그대로 쓸 수 있어야 한다.
   */
  fetchLatest?: () => Promise<RestoredThread>;
}

let seq = 0;
const nextId = () => `m${++seq}`;

export function useAssistantStream({
  askUrl,
  apiFetch,
  storageKey,
  fetchLatest,
}: AssistantStreamOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState(false);
  const conversationId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  // 복원은 **마운트 1회**다. 호출부가 인라인 함수를 넘겨도(identity 매 렌더 변경) 복원이
  // 반복되지 않도록 최신 값을 ref 로만 읽는다.
  const fetchLatestRef = useRef(fetchLatest);
  fetchLatestRef.current = fetchLatest;

  // 탭 저장소에서 직전 대화 복원(주차맵 등에서 뒤로가기). useState 초기값이 아니라 effect 인
  // 이유는 SSR 프리렌더에는 sessionStorage 가 없어서다 — 초기값으로 읽으면 hydration 불일치.
  // 저장된 적이 없을 때(null — 새 탭·브라우저 재시작)만 서버에서 최근 대화를 가져온다 —
  // 2차 폴백(ADR-0027 결정 1). 빈 스레드가 **저장돼 있으면** "새 대화" 마커라 서버 복원을
  // 건너뛴다. 실패는 조용히 빈 대화: 복원은 편의 기능이고 화면을 막으면 안 된다.
  useEffect(() => {
    const thread = readThread(storageKey);
    if (thread !== null) {
      if (thread.messages.length === 0) return; // 새 대화 마커 — 옛 대화를 되살리지 않는다
      conversationId.current = thread.conversationId;
      // 복원한 메시지 id 와 새 메시지 id 가 겹치면 React key 가 충돌한다(전체 리로드 시 seq=0).
      seq = Math.max(seq, thread.messages.length);
      setMessages(thread.messages);
      return;
    }
    const load = fetchLatestRef.current;
    if (!load) return; // 서버 복원 없는 화면
    let alive = true;
    load()
      .then((restored) => {
        if (!alive || restored.messages.length === 0) return;
        conversationId.current = restored.conversationId;
        setMessages(restored.messages);
      })
      .catch(() => {}); // 네트워크·비로그인 — 빈 대화로 시작한다
    return () => {
      alive = false;
    };
  }, [storageKey]);

  // 완료된 메시지만 저장. 빈 대화는 저장하지 않는다 — 마운트 직후 복원 전 스냅샷이
  // 저장본을 지워버리는 순서 문제를 애초에 만들지 않기 위함.
  useEffect(() => {
    // 스트리밍 중에는 건너뛴다 — 토큰마다 직렬화할 이유가 없고, 저장 대상도 그대로다.
    if (messages.some((m) => m.role === "ai" && m.status === "streaming")) return;
    const done = persistableMessages(messages);
    if (done.length === 0) return;
    writeThread(storageKey, { messages: done, conversationId: conversationId.current });
  }, [messages, storageKey]);

  // aiId 메시지에 대한 함수형 갱신(이전 상태 기반 누적 안전).
  const updateAi = useCallback(
    (aiId: string, fn: (m: AiMessage) => AiMessage) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === aiId && m.role === "ai" ? fn(m) : m)),
      );
    },
    [],
  );

  const ask = useCallback(
    async (question: string) => {
      const text = question.trim();
      if (!text || pending) return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const aiId = nextId();
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "user", text },
        {
          id: aiId,
          role: "ai",
          status: "streaming",
          stage: "searching",
          tool: null,
          text: "",
          citations: [],
          steps: [],
        },
      ]);
      setPending(true);

      try {
        const stream = streamAssistant(
          askUrl,
          { question: text, conversation_id: conversationId.current },
          { apiFetch, signal: controller.signal },
        );
        for await (const event of stream) {
          switch (event.type) {
            case "status":
              updateAi(aiId, (m) => ({
                ...m,
                stage: event.stage,
                tool: event.tool,
                steps: appendProgress(m.steps, event.stage, event.tool),
              }));
              break;
            case "token":
              updateAi(aiId, (m) => ({ ...m, text: m.text + event.text }));
              break;
            case "citation":
              updateAi(aiId, (m) => ({ ...m, citations: [...m.citations, event.citation] }));
              break;
            case "done":
              conversationId.current = event.result.conversationId;
              // 서버 최종본이 오면 그것을 정본으로 쓴다 — 누적 토큰은 마스킹된 원문이고
              // 이 값은 unmask 후의 확정 답변이다.
              updateAi(aiId, (m) => ({
                ...m,
                status: "done",
                result: event.result,
                text: event.result.answer ?? m.text,
              }));
              break;
          }
        }
      } catch {
        if (!controller.signal.aborted) {
          updateAi(aiId, (m) => ({
            ...m,
            status: "done",
            error: true,
            text: "일시적인 오류로 답변하지 못했어요. 잠시 후 다시 시도하거나 담당자에게 연결해 드릴게요.",
          }));
        }
      } finally {
        if (abortRef.current === controller) setPending(false);
      }
    },
    [askUrl, apiFetch, pending, updateAi],
  );

  /** 새 대화 — 화면·대화 id·탭 저장본을 비운다. 서버 대화는 삭제하지 않는다(ADR-0027 결정 1). */
  const startNew = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setPending(false);
    setMessages([]);
    conversationId.current = null;
    clearThread(storageKey);
  }, [storageKey]);

  return { messages, ask, pending, startNew };
}
