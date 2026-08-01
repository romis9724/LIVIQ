"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CitationCard, ConfidenceBadge, FeedbackButtons } from "@liviq/ui";
import { getMe } from "@/lib/api";
import { buildComposeHref } from "@/features/inquiries/prefill";
import {
  buildFloorPlanHref,
  deviceLabelsFromCitations,
  isFloorPlanAnswer,
} from "@/features/floor-plan/links";
import { buildParkingHref, isParkingAnswer, spotNosFromCitations } from "@/features/parking/links";
import { answerKind } from "./api";
import { answerBlocks } from "./markdown";
import { progressLabel } from "./progress";
import { StructuredBlock } from "./StructuredBlock";
import { structuredBlocks } from "./structured";
import { groupCitations } from "./sources";
import { type AiMessage, type ChatMessage, useAssistantStream } from "./useAssistantStream";
import "./assistant.css";

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
  const { messages, ask, pending, startNew } = useAssistantStream();
  const [draft, setDraft] = useState("");
  // 헤더 부제용 소속 단지명. 실패하면 단지명 없이 기본 문구만.
  const [tenantName, setTenantName] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 복원된 대화의 첫 표시는 **즉시** 맨 아래로(사용자 지시 2026-08-01) — 진입하자마자
  // 최신 메시지가 보여야 하고, 긴 대화를 애니메이션으로 훑어 내리면 그만큼 기다리게 된다.
  // 이후 대화 중 추가되는 메시지는 기존대로 부드럽게 따라간다.
  const hasScrolledRef = useRef(false);
  useEffect(() => {
    const el = threadRef.current;
    if (!el || messages.length === 0) return;
    el.scrollTo({ top: el.scrollHeight, behavior: hasScrolledRef.current ? "smooth" : "auto" });
    hasScrolledRef.current = true;
  }, [messages]);

  // 되묻기로 끝났으면 바로 답할 수 있게 입력창에 포커스를 준다.
  const last = messages[messages.length - 1];
  const awaitingAnswer = last?.role === "ai" && answerKind(last) === "clarify";
  useEffect(() => {
    if (awaitingAnswer) inputRef.current?.focus();
  }, [awaitingAnswer]);

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
          {/* 부제는 소속 단지명만. 로드 실패하면 아무것도 쓰지 않는다(빈 줄만 남기지 않도록). */}
          {tenantName ? <span className="assistant__sub">{tenantName}</span> : null}
        </span>
        {/* 대화가 서버에 남아 자동 복원되므로(ADR-0027) 끊고 시작할 수단이 필요하다.
            빈 화면에서는 지울 것이 없어 숨긴다. */}
        {isEmpty ? null : (
          <button
            type="button"
            className="btn btn--secondary btn--sm assistant__new"
            onClick={startNew}
            disabled={pending}
          >
            새 대화
          </button>
        )}
      </header>

      <div className="assistant__thread" ref={threadRef} aria-live="polite">
        {isEmpty ? (
          <div className="assistant-empty">
            <span className="assistant-empty__mark" aria-hidden="true">
              L
            </span>
            <p className="assistant-empty__title">무엇이든 물어보세요</p>
            <p className="assistant-empty__desc">
              단지 규약·관리비·공지·시설을 출처와 함께 알려드려요. 아래 입력창에 질문해 주세요.
            </p>
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
                onAsk={submit}
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
          ref={inputRef}
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
  /** 후속 질문 칩 — 칩 문구를 그대로 새 질문으로 보낸다. */
  onAsk: (question: string) => void;
}

function AiRow({ message, question, onAsk }: AiRowProps) {
  const kind = answerKind(message);
  const isInquiry = message.result?.toolPath.includes(INQUIRY_TOOL) ?? false;
  const composeHref = buildComposeHref(question);
  // 주차 도구(빈자리·내 차 위치)가 호출됐으면 지도로 보낸다. 면 번호는 도구 결과 카드에서만
  // 뽑고, 못 뽑아도 CTA 는 띄운다(면 강조 없이 지도만 — H17-2·H19-2).
  const isParking = isParkingAnswer(message.result?.toolPath);
  const parkingHref = buildParkingHref(spotNosFromCitations(message.citations));
  // 세대 평면도 위치 답변은 실제 평면도 뷰어로 보낸다 — 강조 라벨도 도구 카드에서만 뽑는다(H19-6).
  const isFloorPlan = isFloorPlanAnswer(message.result?.toolPath);
  const floorPlanHref = buildFloorPlanHref(deviceLabelsFromCitations(message.citations));
  const blocks = structuredBlocks(message.citations);
  // 폴백에는 칩을 달지 않는다 — 담당자 연락처 안내가 그 자리의 유일한 행동이다.
  // 서버가 이미 질문형만 중복 없이 보낸다(ai_core/suggestions.py) — 프론트 필터는 없앴다.
  const chips = kind === "answered" ? (message.result?.suggestions ?? []) : [];

  return (
    <div className="ai-row">
      <span className="ai-row__avatar" aria-hidden="true">
        L
      </span>
      <div className="ai-row__body">
        {kind === "streaming" ? (
          <>
            <div className="ai-row__hint" role="status">
              <span className="ai-row__pulse" aria-hidden="true" />
              {progressLabel(message.stage, message.tool)} 중…
            </div>
            <div className="bubble-ai">
              <AnswerBody text={message.text} />
              <span className="caret" aria-hidden="true" />
            </div>
          </>
        ) : kind === "clarify" ? (
          // 되묻기: 출처·신뢰도·피드백·칩을 붙이지 않는다 — 근거 있는 답변이 아니라 질문이다.
          <div className="bubble-ai bubble-ai--clarify">
            <p className="clarify__label">
              <span aria-hidden="true">💬</span> 확인이 필요해요
            </p>
            <p className="clarify__question">{message.text}</p>
            <p className="ai-row__hint">아래 입력창에 답해 주시면 이어서 찾아볼게요.</p>
          </div>
        ) : kind === "answered" ? (
          <>
            {/* 출처 카드·신뢰도 배지는 화면에서 뺐다(사용자 지시 2026-08-01) — 답변 한 줄에
                머리말이 두 줄 붙어 정작 답이 밀렸다. **근거 자체를 없앤 게 아니다**: 본문의
                [n] 인용은 그대로고, 근거 없는 답변을 막는 서버 게이트(규칙 1)도 그대로다.
                무엇을 근거로 답했는지는 '답변 과정'을 펼치면 도구 단위로 보인다. */}
            <ProgressSteps steps={message.steps} />
            <div className="bubble-ai">
              <AnswerBody text={message.text} />
              {blocks.map((b) => (
                <StructuredBlock key={b.ref} data={b.data} />
              ))}
            </div>
            {message.result?.needsReview ? (
              <p className="ai-row__review-note">관리사무소 확인 예정인 답변이에요.</p>
            ) : null}
            {/* CTA 와 피드백은 한 줄. CTA 는 왼쪽, 피드백은 오른쪽 끝으로 민다. */}
            <div className="ai-row__actions">
              {isInquiry ? (
                <Link href={composeHref} className="btn btn--secondary btn--sm">
                  <span aria-hidden="true">📝</span> 민원 접수하기
                </Link>
              ) : null}
              {isParking ? (
                <Link href={parkingHref} className="btn btn--secondary btn--sm">
                  <span aria-hidden="true">🅿️</span> 주차위치 보기
                </Link>
              ) : null}
              {isFloorPlan ? (
                <Link href={floorPlanHref} className="btn btn--secondary btn--sm">
                  <span aria-hidden="true">🏠</span> 평면도 보기
                </Link>
              ) : null}
              <FeedbackButtons className="ai-row__feedback" />
            </div>
            {/* 칩은 액션 줄 **아래**(사용자 지시) — 이어서 물어보기는 이 답변을 다 읽고
                평가까지 한 다음의 행동이다. */}
            <SuggestionChips chips={chips} onAsk={onAsk} />
          </>
        ) : (
          <>
            <ProgressSteps steps={message.steps} />
            <ConfidenceBadge status="handoff" />
            <div className="bubble-ai">
              <p>{message.error ? message.text : fallbackText(message.result?.fallbackReason ?? null)}</p>
              {groupCitations(message.citations).map((s) => (
                <CitationCard key={s.ref} title={s.title} meta={s.details.join(" · ")} />
              ))}
              {/* 연락처 안내가 폴백의 본체이자 유일한 행동이다. 버튼은 두지 않는다 —
                  "담당자 연결"은 연결해 줄 채널이 없었고, "민원 접수하기"는 답을 못 준 화면에서
                  민원으로 떠넘기는 인상이라 뺐다(사용자 지시). 접수 CTA 는 답변 경로에만 남는다. */}
              <div className="handoff-contact">관리사무소 · 평일 09:00~18:00 · 담당 김*수 소장</div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * 답변 본문 — 문단·목록만 렌더한다(markdown.ts). 마크다운 라이브러리도
 * `dangerouslySetInnerHTML` 도 쓰지 않는다: 모델 출력은 신뢰 경계 밖이다(XSS).
 */
function AnswerBody({ text }: { text: string }) {
  return (
    <>
      {answerBlocks(text).map((block, i) =>
        block.kind === "ul" ? (
          <ul key={`ul-${i}`} className="answer-list">
            {block.items.map((item, j) => (
              <li key={`${j}-${item}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p key={`p-${i}`} className="answer-text">
            {block.text}
          </p>
        ),
      )}
    </>
  );
}

/**
 * 답변 과정 — 기본 접힘. `<details>` 를 쓰는 이유: 키보드 열고 닫기·스크린리더 상태 노출을
 * 브라우저가 공짜로 해준다(자체 토글 상태·aria-expanded 를 만들 이유가 없다).
 */
function ProgressSteps({ steps }: { steps: readonly string[] }) {
  if (steps.length === 0) return null;
  return (
    <details className="ai-steps">
      <summary className="ai-steps__summary">답변 과정 {steps.length}단계</summary>
      <ol className="ai-steps__list">
        {steps.map((step, i) => (
          <li key={`${i}-${step}`}>{step}</li>
        ))}
      </ol>
    </details>
  );
}

/**
 * 출처 우선 배치(H18-3 ③) — 답변 위 가로 스크롤 **한 줄**. 375px 에서는 이 줄 안에서만 스크롤된다.
 *
 * "출처 N건" 라벨 줄은 없앴다(사용자 지적) — 라벨 줄 + 카드 줄 + 카드 안 "출처" 배지로 같은
 * 말이 세 번 나오면서 두 줄을 먹었다. 건수는 카드가 눈에 보이고, 스크린리더에는 이 섹션의
 * aria-label 이 그대로 전달한다.
 */

/** 맥락 기반 후속 질문 칩 — 누르면 그 문구로 새 질문을 보낸다. 비면 아무것도 렌더하지 않는다. */
function SuggestionChips({
  chips,
  onAsk,
}: {
  chips: readonly string[];
  onAsk: (question: string) => void;
}) {
  if (chips.length === 0) return null;
  return (
    <nav className="ai-chips" aria-label="이어서 물어보기">
      {chips.map((chip) => (
        <button key={chip} type="button" className="ai-chip" onClick={() => onAsk(chip)}>
          {chip}
        </button>
      ))}
    </nav>
  );
}
