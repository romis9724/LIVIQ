"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { type Citation, type DoneResult, type Stage, streamAsk } from "./api";
import { persistableMessages, readThread, writeThread } from "./session-store";

export interface AiMessage {
  id: string;
  role: "ai";
  status: "streaming" | "done";
  stage: Stage;
  text: string;
  citations: Citation[];
  result?: DoneResult;
  error?: boolean;
}

export interface UserMessage {
  id: string;
  role: "user";
  text: string;
}

export type ChatMessage = AiMessage | UserMessage;

let seq = 0;
const nextId = () => `m${++seq}`;

export function useAssistantStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState(false);
  const conversationId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  // 탭 저장소에서 직전 대화 복원(주차맵 등에서 뒤로가기). useState 초기값이 아니라 effect 인
  // 이유는 SSR 프리렌더에는 sessionStorage 가 없어서다 — 초기값으로 읽으면 hydration 불일치.
  useEffect(() => {
    const thread = readThread();
    if (thread.messages.length === 0) return;
    conversationId.current = thread.conversationId;
    // 복원한 메시지 id 와 새 메시지 id 가 겹치면 React key 가 충돌한다(전체 리로드 시 seq=0).
    seq = Math.max(seq, thread.messages.length);
    setMessages(thread.messages);
  }, []);

  // 완료된 메시지만 저장. 빈 대화는 저장하지 않는다 — 마운트 직후 복원 전 스냅샷이
  // 저장본을 지워버리는 순서 문제를 애초에 만들지 않기 위함.
  useEffect(() => {
    // 스트리밍 중에는 건너뛴다 — 토큰마다 직렬화할 이유가 없고, 저장 대상도 그대로다.
    if (messages.some((m) => m.role === "ai" && m.status === "streaming")) return;
    const done = persistableMessages(messages);
    if (done.length === 0) return;
    writeThread({ messages: done, conversationId: conversationId.current });
  }, [messages]);

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
        { id: aiId, role: "ai", status: "streaming", stage: "searching", text: "", citations: [] },
      ]);
      setPending(true);

      try {
        for await (const event of streamAsk(text, {
          conversationId: conversationId.current,
          signal: controller.signal,
        })) {
          switch (event.type) {
            case "status":
              updateAi(aiId, (m) => ({ ...m, stage: event.stage }));
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
    [pending, updateAi],
  );

  return { messages, ask, pending };
}
