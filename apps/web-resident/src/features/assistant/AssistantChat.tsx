"use client";

import { useEffect, useRef, useState } from "react";
import { CitationCard, ConfidenceBadge, FeedbackButtons } from "@liviq/ui";
import "./assistant.css";

type Resolution =
  | { kind: "answered"; text: string; citation: { title: string; meta: string } }
  | { kind: "fallback"; text: string };

interface ChatMessage {
  id: string;
  role: "user" | "ai";
  status: "streaming" | "done";
  resolution?: Resolution;
  userText?: string;
}

const SUGGESTIONS = ["관리비 이의신청 방법", "엘리베이터 점검일", "분리수거 배출 시간"];
const FOLLOW_UPS = ["관리비 이의신청 방법", "엘리베이터 점검일", "분리수거 배출 시간"];

const FALLBACK_KEYWORDS = ["보험", "한도", "누수", "전기차", "충전"];

/** 질문 내용으로 응답을 결정한다(백엔드 연동 전 결정적 목업). 근거 없으면 폴백. */
function resolve(question: string): Resolution {
  if (FALLBACK_KEYWORDS.some((k) => question.includes(k))) {
    return {
      kind: "fallback",
      text: "이 질문은 근거 문서에서 정확한 내용을 찾지 못했어요. 추측해서 답하지 않고 관리사무소 담당자에게 연결해 드릴게요.",
    };
  }
  return {
    kind: "answered",
    text: "규정상 평일 09:00~18:00에 인테리어 공사가 가능한 것으로 보입니다. 주말·공휴일은 제한됩니다. 정확한 적용은 관리사무소에 확인해 주세요.",
    citation: { title: "관리규약 제32조 (공사 시간 제한)", meta: "12페이지 · 2024.03 개정본" },
  };
}

let seq = 0;
const nextId = () => `m${++seq}`;

export function AssistantChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const threadRef = useRef<HTMLDivElement>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const ask = (question: string) => {
    const text = question.trim();
    if (!text) return;
    const aiId = nextId();
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", status: "done", userText: text },
      { id: aiId, role: "ai", status: "streaming" },
    ]);
    setDraft("");
    const t = setTimeout(() => {
      const resolution = resolve(text);
      setMessages((prev) =>
        prev.map((m) => (m.id === aiId ? { ...m, status: "done", resolution } : m)),
      );
    }, 1300);
    timers.current.push(t);
  };

  const isEmpty = messages.length === 0;

  return (
    <section className="assistant" aria-label="AI 비서 대화">
      <header className="assistant__header">
        <span className="assistant__mark" aria-hidden="true">
          L
        </span>
        <span className="assistant__heading">
          <span className="assistant__title">AI 비서</span>
          <span className="assistant__sub">래미안 한강 1단지 · 출처 기반 응대</span>
        </span>
      </header>

      <div className="assistant__thread" ref={threadRef} aria-live="polite">
        {isEmpty ? (
          <div className="assistant-empty">
            <span className="assistant-empty__mark" aria-hidden="true">
              L
            </span>
            <p className="assistant-empty__title">무엇이든 물어보세요</p>
            <p className="assistant-empty__desc">
              단지 규약·관리비·공지·시설을 출처와 함께 알려드려요. 아래에서 골라 시작해 보세요.
            </p>
            <div className="chips">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="chip" onClick={() => ask(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="bubble-user">
                {m.userText}
              </div>
            ) : (
              <AiMessage key={m.id} message={m} onChip={ask} />
            ),
          )
        )}
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          ask(draft);
        }}
      >
        <label htmlFor="assistant-ask" className="sr-only">
          질문 입력
        </label>
        <input
          id="assistant-ask"
          type="text"
          className="composer__input"
          placeholder="단지 규약·관리비·시설 무엇이든"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoComplete="off"
        />
        <button type="submit" className="composer__send" aria-label="질문 보내기" disabled={!draft.trim()}>
          ↑
        </button>
      </form>
    </section>
  );
}

function AiMessage({ message, onChip }: { message: ChatMessage; onChip: (q: string) => void }) {
  return (
    <div className="ai-row">
      <span className="ai-row__avatar" aria-hidden="true">
        L
      </span>
      <div className="ai-row__body">
        {message.status === "streaming" ? (
          <>
            <div className="bubble-ai">
              규정상 평일 09:00~18:00에는 인테리어 공사가 가능
              <span className="caret" aria-hidden="true" />
            </div>
            <div className="ai-row__hint">
              <span aria-hidden="true">📄</span> 출처 문서 확인 중…
            </div>
          </>
        ) : message.resolution?.kind === "answered" ? (
          <>
            <ConfidenceBadge status="answered" />
            <div className="bubble-ai">
              <p>{message.resolution.text}</p>
              <CitationCard
                title={message.resolution.citation.title}
                meta={message.resolution.citation.meta}
                href="#"
              />
            </div>
            <FeedbackButtons />
            <div className="ai-row__followups">
              <span className="ai-row__followups-label">이어서 물어보기</span>
              <div className="chips">
                {FOLLOW_UPS.map((c) => (
                  <button key={c} type="button" className="chip" onClick={() => onChip(c)}>
                    {c}
                  </button>
                ))}
              </div>
            </div>
          </>
        ) : (
          <>
            <ConfidenceBadge status="handoff" />
            <div className="bubble-ai">
              <p>{message.resolution?.text}</p>
              <div className="handoff-contact">관리사무소 · 평일 09:00~18:00 · 담당 김*수 소장</div>
              <div className="handoff-actions">
                <button type="button" className="btn btn--primary">
                  담당자 연결
                </button>
                <button type="button" className="btn btn--secondary">
                  1:1 문의 남기기
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
