"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CitationCard, ConfidenceBadge, FeedbackButtons } from "@liviq/ui";
import { getMe } from "@/lib/api";
import { buildComposeHref } from "@/features/inquiries/prefill";
import { type AiMessage, type ChatMessage, useAssistantStream } from "./useAssistantStream";
import "./assistant.css";

const SUGGESTIONS = ["관리비 이의신청 방법", "엘리베이터 점검일", "분리수거 배출 시간"];

const STAGE_HINT: Record<string, string> = {
  searching: "출처 문서 찾는 중…",
  generating: "답변 작성 중…",
  verifying: "근거 확인 중…",
};

const FALLBACK_DEFAULT = "확실한 답을 드리기 어려워요. 관리사무소 담당자에게 연결해 드릴게요.";

/** 이 도구가 호출됐다는 것 = 모델이 민원성 질의로 라우팅했다는 뜻(ADR-0024). */
const INQUIRY_TOOL = "search_similar_inquiries";

const FALLBACK_TEXT: Record<string, string> = {
  no_evidence: "근거 문서에서 정확한 내용을 찾지 못했어요. 추측하지 않고 관리사무소 담당자에게 연결해 드릴게요.",
  llm_unavailable: "AI 요약이 일시적으로 어려워 검색된 근거만 안내해요. 잠시 후 다시 시도해 주세요.",
  low_confidence: FALLBACK_DEFAULT,
  masking_failed: "개인정보 보호를 위해 이 질문은 담당자에게 직접 연결해 드릴게요.",
};

function fallbackText(reason: string | null): string {
  return (reason ? FALLBACK_TEXT[reason] : undefined) ?? FALLBACK_DEFAULT;
}

/**
 * index 위치의 AI 답변이 어떤 질문에 대한 것인지 — 바로 앞의 user 메시지를 거슬러 찾는다.
 * 접수 링크 프리필에 **질문 원문**을 쓰기 위한 것(AI 답변은 쓰지 않는다).
 */
function questionBefore(messages: readonly ChatMessage[], index: number): string {
  for (let i = index - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m?.role === "user") return m.text;
  }
  return "";
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
          messages.map((m: ChatMessage, i: number) =>
            m.role === "user" ? (
              <div key={m.id} className="bubble-user">
                {m.text}
              </div>
            ) : (
              <AiRow
                key={m.id}
                message={m}
                question={questionBefore(messages, i)}
                onChip={submit}
              />
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

interface AiRowProps {
  message: AiMessage;
  /** 이 답변을 유발한 질문 원문 — 민원 접수 링크 프리필용. */
  question: string;
  onChip: (q: string) => void;
}

function AiRow({ message, question, onChip }: AiRowProps) {
  const streaming = message.status === "streaming";
  const answered = message.result?.status === "answered" && !message.error;
  const isInquiry = message.result?.toolPath.includes(INQUIRY_TOOL) ?? false;
  const composeHref = buildComposeHref(question);

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
            {isInquiry ? (
              <Link href={composeHref} className="btn btn--secondary btn--sm ai-row__cta">
                민원 접수하기
              </Link>
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
                {/* AI 가 답하지 못한 건은 접수로 넘긴다 — 질문 원문이 프리필된 폼으로(ADR-0024). */}
                <Link href={composeHref} className="btn btn--secondary">
                  민원 접수하기
                </Link>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
