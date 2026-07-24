"use client";

import { useEffect, useRef, useState } from "react";
import { CitationCard, ConfidenceBadge, FeedbackButtons } from "@liviq/ui";
import { getMe } from "@/lib/api";
import { type AiMessage, type ChatMessage, useAssistantStream } from "./useAssistantStream";
import "./assistant.css";

const SUGGESTIONS = ["관리비 이의신청 방법", "엘리베이터 점검일", "분리수거 배출 시간"];

const STAGE_HINT: Record<string, string> = {
  searching: "출처 문서 찾는 중…",
  generating: "답변 작성 중…",
  verifying: "근거 확인 중…",
};

const FALLBACK_DEFAULT = "확실한 답을 드리기 어려워요. 관리사무소 담당자에게 연결해 드릴게요.";

const FALLBACK_TEXT: Record<string, string> = {
  no_evidence: "근거 문서에서 정확한 내용을 찾지 못했어요. 추측하지 않고 관리사무소 담당자에게 연결해 드릴게요.",
  llm_unavailable: "AI 요약이 일시적으로 어려워 검색된 근거만 안내해요. 잠시 후 다시 시도해 주세요.",
  low_confidence: FALLBACK_DEFAULT,
  masking_failed: "개인정보 보호를 위해 이 질문은 담당자에게 직접 연결해 드릴게요.",
};

function fallbackText(reason: string | null): string {
  return (reason ? FALLBACK_TEXT[reason] : undefined) ?? FALLBACK_DEFAULT;
}

export function AssistantChat() {
  const { messages, ask, pending } = useAssistantStream();
  const [draft, setDraft] = useState("");
  // 헤더 부제용 소속 단지명. 실패하면 단지명 없이 기본 문구만.
  const [tenantName, setTenantName] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    let alive = true;
    getMe()
      .then((me) => alive && setTenantName(me.tenantName))
      .catch(() => {}); // 실패 시 기본 부제 유지
    return () => {
      alive = false;
    };
  }, []);

  const submit = (question: string) => {
    void ask(question);
    setDraft("");
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
          <span className="assistant__sub">
            {tenantName ? `${tenantName} · 출처 기반 응대` : "출처 기반 응대"}
          </span>
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
                <button key={s} type="button" className="chip" onClick={() => submit(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m: ChatMessage) =>
            m.role === "user" ? (
              <div key={m.id} className="bubble-user">
                {m.text}
              </div>
            ) : (
              <AiRow key={m.id} message={m} onChip={submit} />
            ),
          )
        )}
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          submit(draft);
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
        <button
          type="submit"
          className="composer__send"
          aria-label="질문 보내기"
          disabled={!draft.trim() || pending}
        >
          ↑
        </button>
      </form>
    </section>
  );
}

function AiRow({ message, onChip }: { message: AiMessage; onChip: (q: string) => void }) {
  const streaming = message.status === "streaming";
  const answered = message.result?.status === "answered" && !message.error;

  return (
    <div className="ai-row">
      <span className="ai-row__avatar" aria-hidden="true">
        L
      </span>
      <div className="ai-row__body">
        {streaming ? (
          <>
            <div className="bubble-ai">
              {message.text}
              <span className="caret" aria-hidden="true" />
            </div>
            <div className="ai-row__hint">
              <span aria-hidden="true">📄</span> {STAGE_HINT[message.stage] ?? "처리 중…"}
            </div>
          </>
        ) : answered ? (
          <>
            <ConfidenceBadge status={message.result?.needsReview ? "review" : "answered"} />
            <div className="bubble-ai">
              <p>{message.text}</p>
              {message.citations.map((c) => (
                <CitationCard
                  key={c.ref}
                  title={c.documentTitle}
                  meta={[c.clause, c.page != null ? `${c.page}p` : null]
                    .filter(Boolean)
                    .join(" · ")}
                  href="#"
                />
              ))}
            </div>
            {message.result?.needsReview ? (
              <p className="ai-row__review-note">관리사무소 확인 예정인 답변이에요.</p>
            ) : null}
            <FeedbackButtons />
            <div className="ai-row__followups">
              <span className="ai-row__followups-label">이어서 물어보기</span>
              <div className="chips">
                {SUGGESTIONS.map((c) => (
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
              <p>{message.error ? message.text : fallbackText(message.result?.fallbackReason ?? null)}</p>
              {message.citations.map((c) => (
                <CitationCard
                  key={c.ref}
                  title={c.documentTitle}
                  meta={[c.clause, c.page != null ? `${c.page}p` : null].filter(Boolean).join(" · ")}
                  href="#"
                />
              ))}
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
