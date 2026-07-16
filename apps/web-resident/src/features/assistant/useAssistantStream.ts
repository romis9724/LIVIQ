"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { type Citation, type DoneResult, type Stage, streamAsk } from "./api";

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
              updateAi(aiId, (m) => ({ ...m, status: "done", result: event.result }));
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
