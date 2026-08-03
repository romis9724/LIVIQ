"use client";

// 관리자 홈 — 왼쪽 AI 비서 채팅 + 오른쪽 민원현황 패널(ADR-0028).
// 채팅 메커니즘(SSE·저장·마크다운·구조화 블록)은 @liviq/ui 공용, 여기는 조립만 한다.
// 말풍선·진행 단계 스타일은 입주민과 같은 assistant.css(전역 번들)를 그대로 쓴다.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  AnswerBody,
  CitationCard,
  FeedbackButtons,
  ProgressSteps,
  StructuredBlock,
  SuggestionChips,
  type AiMessage,
  type ChatMessage,
  answerKind,
  groupCitations,
  progressLabel,
  structuredBlocks,
  useAssistantStream,
} from "@liviq/ui";

import {
  briefingPrompt,
  isBriefingPrompt,
  isFacilityAnswer,
  isInquirySummaryAnswer,
  isRecentNoticesAnswer,
} from "./briefing";
import {
  buildLongtermParkingHref,
  isLongtermParkingAnswer,
  longtermSpotNos,
} from "@/features/parking/assistant-links";
import {
  buildTwinHouseholdHref,
  householdDeviceTarget,
  isHouseholdDevicesAnswer,
} from "@/features/twin/assistant-links";
import { ADMIN_ASSISTANT_STREAM_OPTIONS } from "./client";
import { InquiryStatusPanel } from "./InquiryStatusPanel";
import "./admin-assistant.css";

const FALLBACK_DEFAULT = "확실한 답을 드리기 어려워요. 민원 관리 화면에서 직접 확인해 주세요.";

// 폴백 사유별 안내 — 톤은 입주민(#140 대화체)과 맞추되, 내용은 관리자 맥락을 유지한다:
// "담당자에게 연결"이 아니라 관리자가 직접 볼 화면을 가리킨다(H20-12).
const FALLBACK_TEXT: Record<string, string> = {
  no_evidence:
    "죄송해요, 근거가 될 문서·데이터를 찾지 못했어요. 질문을 조금 더 구체적으로 적어 주시면 다시 찾아볼게요.",
  llm_unavailable: "AI 요약이 일시적으로 어려워 찾은 근거만 안내해요. 잠시 후 다시 시도해 주세요.",
  low_confidence: FALLBACK_DEFAULT,
  masking_failed: "개인정보가 섞여 있어 이 질문은 처리하지 않았어요(규칙 2).",
};

function fallbackText(reason: string | null): string {
  return (reason ? FALLBACK_TEXT[reason] : undefined) ?? FALLBACK_DEFAULT;
}

export function AdminAssistant() {
  const { messages, ask, pending, startNew, restored } = useAssistantStream(
    ADMIN_ASSISTANT_STREAM_OPTIONS,
  );
  const [draft, setDraft] = useState("");
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 진입 브리핑 — **마운트 1회**만(ADR-0028 결정 3). '새 대화'로 비운 화면에 자동 질의가
  // 끼어들면 안 되므로 "빈 대화로 전이할 때마다"가 아니라 ref 로 한 번만 잠근다.
  // 게이트는 훅의 `restored` 다(H20-3): 복원(탭 저장 → 서버 당일 대화)이 **끝난 뒤**에도
  // 대화가 비어 있을 때만 발동한다. restored 전에는 messages 가 항상 빈 배열이라(레이스)
  // 그때 판정하면 복원된 대화 위에 브리핑이 끼어든다.
  // ask 는 타이머로 예약하고 cleanup 에서 취소한다 — StrictMode 의 effect→cleanup→effect 에서
  // 즉시 ask 하면 첫 실행의 요청이 cleanup(abort)에 죽고, ref 가드가 재발동까지 막아
  // "근거 검색 중"이 영구히 남는다(dev 실측). 타이머면 첫 실행은 시작 전에 취소된다.
  // 실패는 훅의 기존 오류 말풍선에 맡긴다 — 화면을 막지 않는다.
  const briefedRef = useRef(false);
  const messageCount = messages.length;
  useEffect(() => {
    if (briefedRef.current || !restored) return;
    if (messageCount > 0) {
      briefedRef.current = true; // 복원된 대화가 있다 — 이후 '새 대화'로 비워도 발동 금지
      return;
    }
    const timer = setTimeout(() => {
      briefedRef.current = true;
      // 되묻기를 끄고 보낸다 — 화면을 연 직후의 자동 질의라 되물어도 답할 사람이 없다(H20-3).
      void ask(briefingPrompt(new Date()), { allow_clarify: false });
    }, 0);
    return () => clearTimeout(timer);
  }, [ask, restored, messageCount]);

  // 새 메시지를 따라 맨 아래로.
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

  const submit = (question: string) => {
    void ask(question);
    setDraft("");
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="adm-assist">
      <h1 id="main" className="sr-only">
        AI 비서
      </h1>

      <section className="assistant adm-assist__chat" aria-label="AI 비서 대화">
        {/* 관리자 헤더에는 L 마크를 두지 않는다 — AdminShell 사이드바가 이미 LIVIQ 마크를
            그려서 모바일에선 두 개가 세로로 겹쳐 보였다(실화면 보고). 입주민은 셸에 로고가
            없어 마크가 유일한 브랜딩이라 공용 assistant.css·AssistantChat 은 그대로 둔다. */}
        <header className="assistant__header">
          <span className="assistant__heading">
            <span className="assistant__title">AI 비서</span>
            <span className="assistant__sub">관리소 운영 현황을 근거와 함께 알려드려요</span>
          </span>
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
          {/* 마운트 직후엔 브리핑이 곧바로 채우므로 이 빈 상태는 '새 대화' 뒤에 보인다. */}
          {isEmpty ? (
            <div className="assistant-empty">
              <span className="assistant-empty__mark" aria-hidden="true">
                L
              </span>
              <p className="assistant-empty__title">무엇을 확인해 드릴까요?</p>
              <p className="assistant-empty__desc">
                민원 현황·시설 점검·문서 규정을 출처와 함께 알려드려요. 아래 입력창에 질문해 주세요.
              </p>
            </div>
          ) : null}
          {messages.map((m: ChatMessage) =>
            m.role === "user" ? (
              // 자동 브리핑의 사용자 말풍선은 숨긴다 — 관리자가 친 질문이 아니다(ADR-0028 결정 3).
              // 공용 훅 API 를 건드리지 않는 조립 계층 해법이고, sessionStorage 복원본도 같은
              // 규칙으로 다시 숨겨진다(판정은 날짜가 아니라 문구 꼬리 — briefing.ts).
              isBriefingPrompt(m.text) ? null : (
                <div key={m.id} className="bubble-user">
                  {m.text}
                </div>
              )
            ) : (
              <AiRow key={m.id} message={m} onAsk={submit} />
            ),
          )}
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            submit(draft);
          }}
        >
          <label htmlFor="admin-assistant-ask" className="sr-only">
            질문 입력
          </label>
          <input
            id="admin-assistant-ask"
            ref={inputRef}
            type="text"
            className="composer__input"
            placeholder="민원 현황·시설 점검·문서 무엇이든"
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

      <InquiryStatusPanel />
    </div>
  );
}

interface AiRowProps {
  message: AiMessage;
  /** 후속 질문 칩 — 칩 문구를 그대로 새 질문으로 보낸다. */
  onAsk: (question: string) => void;
}

function AiRow({ message, onAsk }: AiRowProps) {
  const kind = answerKind(message);
  const blocks = structuredBlocks(message.citations);
  // 폴백에는 칩을 달지 않는다 — 서버가 이미 질문형만 중복 없이 보낸다(ai_core/suggestions.py).
  const chips = kind === "answered" ? (message.result?.suggestions ?? []) : [];
  const toolPath = message.result?.toolPath;
  const isSummary = isInquirySummaryAnswer(toolPath);
  // 장기주차 답변 → 3D 비콘 딥링크(ADM-1). 면 번호는 도구 카드 quote 확정값에서만 뽑는다.
  const longtermSpots = isLongtermParkingAnswer(toolPath) ? longtermSpotNos(message.citations) : [];
  // 시설·공지 답변 → 해당 화면으로(H20-12). 판정은 도구 이름만, 파라미터는 없다.
  const isFacility = isFacilityAnswer(toolPath);
  const isNotices = isRecentNoticesAnswer(toolPath);
  // 세대 설비 위치 답변 → 트윈의 그 세대 평면도(H20-17). 동·호수·강조 라벨은 도구 카드
  // data(서버 확정값)에서만 뽑는다 — 도구가 답을 못 냈으면 카드가 없어 CTA 도 없다.
  const householdTarget = isHouseholdDevicesAnswer(toolPath)
    ? householdDeviceTarget(message.citations)
    : null;

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
              <AnswerBody text={message.text} citations={message.citations} />
              <span className="caret" aria-hidden="true" />
            </div>
          </>
        ) : kind === "clarify" ? (
          // 되묻기: 출처·피드백·칩을 붙이지 않는다 — 근거 있는 답변이 아니라 질문이다.
          <div className="bubble-ai bubble-ai--clarify">
            <p className="clarify__label">
              <span aria-hidden="true">💬</span> 확인이 필요해요
            </p>
            <p className="clarify__question">{message.text}</p>
            <p className="ai-row__hint">아래 입력창에 답해 주시면 이어서 찾아볼게요.</p>
          </div>
        ) : kind === "answered" ? (
          <>
            <ProgressSteps steps={message.steps} />
            <div className="bubble-ai">
              <AnswerBody text={message.text} citations={message.citations} />
              {blocks.map((b) => (
                <StructuredBlock key={b.ref} data={b.data} />
              ))}
            </div>
            <div className="ai-row__actions">
              {isSummary ? (
                <Link href="/inquiry-status" className="btn btn--secondary btn--sm">
                  <span aria-hidden="true">📊</span> 민원현황 열기
                </Link>
              ) : null}
              {longtermSpots.length > 0 ? (
                <Link
                  href={buildLongtermParkingHref(longtermSpots)}
                  className="btn btn--secondary btn--sm"
                >
                  <span aria-hidden="true">🅿️</span> 주차장 3D에서 보기
                </Link>
              ) : null}
              {isFacility ? (
                <Link href="/facilities" className="btn btn--secondary btn--sm">
                  <span aria-hidden="true">🔧</span> 시설관리에서 보기
                </Link>
              ) : null}
              {isNotices ? (
                <Link href="/notices" className="btn btn--secondary btn--sm">
                  <span aria-hidden="true">📢</span> 공지사항 열기
                </Link>
              ) : null}
              {householdTarget ? (
                <Link
                  href={buildTwinHouseholdHref(householdTarget)}
                  className="btn btn--secondary btn--sm"
                >
                  <span aria-hidden="true">🏠</span> 평면도 보기
                </Link>
              ) : null}
              <FeedbackButtons className="ai-row__feedback" />
            </div>
            <SuggestionChips chips={chips} onAsk={onAsk} />
          </>
        ) : (
          <>
            <ProgressSteps steps={message.steps} />
            <div className="bubble-ai">
              <p>
                {message.error ? message.text : fallbackText(message.result?.fallbackReason ?? null)}
              </p>
              {groupCitations(message.citations).map((s) => (
                <CitationCard key={s.ref} title={s.title} meta={s.details.join(" · ")} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
