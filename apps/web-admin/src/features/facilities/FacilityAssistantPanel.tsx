"use client";

import { Button, CitationCard, ConfidenceBadge } from "@liviq/ui";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AssistantCitation,
  type DoneResult,
  type Stage,
  streamFacilityAssistant,
} from "./assistant";

const STAGE_HINT: Record<Stage, string> = {
  searching: "유사 장애·이력 조회 중…",
  generating: "가능 원인 후보 작성 중…",
  verifying: "근거 확인 중…",
};

const FALLBACK_DEFAULT =
  "이력만으로는 원인 후보를 제시하기 어렵습니다. 담당자가 직접 점검·확인해 주세요.";

const FALLBACK_TEXT: Record<string, string> = {
  no_evidence: "관련 장애·정비 이력을 찾지 못했습니다. 추정 없이 담당자 점검을 권장합니다.",
  llm_unavailable: "AI 요약이 일시적으로 어려워 조회된 이력만 안내합니다. 잠시 후 다시 시도해 주세요.",
  low_confidence: FALLBACK_DEFAULT,
  masking_failed: "개인정보 보호를 위해 이 질문은 AI로 처리하지 않았습니다.",
};

function fallbackText(reason: string | null): string {
  return (reason ? FALLBACK_TEXT[reason] : undefined) ?? FALLBACK_DEFAULT;
}

interface AssistantState {
  status: "idle" | "streaming" | "done";
  stage: Stage;
  text: string;
  citations: AssistantCitation[];
  result?: DoneResult;
  error?: boolean;
}

const INITIAL: AssistantState = {
  status: "idle",
  stage: "searching",
  text: "",
  citations: [],
};

const SUGGESTIONS = [
  "승강기 덜컹 소음 원인 후보",
  "지하 배수펌프 반복 정지 이력",
  "점검 기한 임박 설비",
];

/** 시설 AI 도우미 — 질문→SSE 토큰 스트림→가능 원인 후보 + 출처 카드(단정 금지). */
export function FacilityAssistantPanel() {
  const [state, setState] = useState<AssistantState>(INITIAL);
  const [draft, setDraft] = useState("");
  const conversationId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const ask = useCallback(async (question: string) => {
    const text = question.trim();
    if (!text) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ ...INITIAL, status: "streaming" });

    try {
      for await (const event of streamFacilityAssistant(text, {
        conversationId: conversationId.current,
        signal: controller.signal,
      })) {
        switch (event.type) {
          case "status":
            setState((s) => ({ ...s, stage: event.stage }));
            break;
          case "token":
            setState((s) => ({ ...s, text: s.text + event.text }));
            break;
          case "citation":
            setState((s) => ({ ...s, citations: [...s.citations, event.citation] }));
            break;
          case "done":
            conversationId.current = event.result.conversationId;
            setState((s) => ({ ...s, status: "done", result: event.result }));
            break;
        }
      }
    } catch {
      if (!controller.signal.aborted) {
        setState((s) => ({ ...s, status: "done", error: true }));
      }
    }
  }, []);

  const busy = state.status === "streaming";

  const submit = (question: string) => {
    void ask(question);
    setDraft("");
  };

  const answered = state.result?.status === "answered" && !state.error;

  return (
    <section className="fac-ai" aria-label="시설 AI 도우미">
      <header className="fac-ai__head">
        <span className="fac-ai__mark" aria-hidden="true">
          AI
        </span>
        <div>
          <div className="fac-ai__title">시설 AI 도우미</div>
          <p className="fac-ai__sub">유사 장애·정비 이력으로 가능 원인 후보를 제시합니다(단정 없음).</p>
        </div>
      </header>

      <form
        className="fac-ai__composer"
        onSubmit={(e) => {
          e.preventDefault();
          submit(draft);
        }}
      >
        <label htmlFor="fac-ai-ask" className="sr-only">
          시설 질문 입력
        </label>
        <input
          id="fac-ai-ask"
          type="text"
          className="fac-ai__input"
          placeholder="증상·설비를 입력하면 원인 후보를 찾습니다"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoComplete="off"
          disabled={busy}
        />
        <Button variant="primary" type="submit" disabled={!draft.trim() || busy}>
          질문
        </Button>
      </form>

      {state.status === "idle" ? (
        <div className="fac-ai__chips">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="fac-ai__chip" onClick={() => submit(s)}>
              {s}
            </button>
          ))}
        </div>
      ) : (
        <div className="fac-ai__answer" aria-live="polite">
          {busy ? (
            <>
              <p className="fac-ai__text">
                {state.text}
                <span className="fac-ai__caret" aria-hidden="true" />
              </p>
              <div className="fac-ai__hint">{STAGE_HINT[state.stage]}</div>
            </>
          ) : answered ? (
            <>
              <ConfidenceBadge status={state.result?.needsReview ? "review" : "answered"} />
              <p className="fac-ai__text">{state.text}</p>
              {state.citations.map((c) => (
                <CitationCard
                  key={c.ref}
                  title={c.documentTitle}
                  meta={[c.quote, c.clause, c.page != null ? `${c.page}p` : null]
                    .filter(Boolean)
                    .join(" · ")}
                  href="#"
                />
              ))}
            </>
          ) : (
            <>
              <ConfidenceBadge status="handoff" />
              <p className="fac-ai__text">{fallbackText(state.result?.fallbackReason ?? null)}</p>
              {state.citations.map((c) => (
                <CitationCard
                  key={c.ref}
                  title={c.documentTitle}
                  meta={[c.quote, c.clause].filter(Boolean).join(" · ")}
                  href="#"
                />
              ))}
            </>
          )}
        </div>
      )}
    </section>
  );
}
