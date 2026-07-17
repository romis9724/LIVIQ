"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, CitationCard, ConfidenceBadge, Dialog, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";

import { ApiError, createNoticeDraft, publishNotice, type NoticeDraft } from "@/lib/api";
import { addKeyword, canGenerate, confidenceStatus, removeKeyword, MAX_KEYWORDS } from "./data";
import "./notice-composer.css";

type Step = "keyword" | "drafting" | "review";

const STEP_LABELS: Record<Step, string> = {
  keyword: "키워드",
  drafting: "AI 초안",
  review: "검수",
};
const ORDER: Step[] = ["keyword", "drafting", "review"];

const ADD_REASON: Record<"empty" | "duplicate" | "max", string> = {
  empty: "키워드를 입력하세요.",
  duplicate: "이미 추가한 키워드입니다.",
  max: `키워드는 최대 ${MAX_KEYWORDS}개까지 추가할 수 있습니다.`,
};

const TOAST_DURATION_MS = 3200;

interface ToastState {
  message: string;
  tone: ToastTone;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function NoticeComposer() {
  const [step, setStep] = useState<Step>("keyword");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [genError, setGenError] = useState<string | null>(null);
  const [draft, setDraft] = useState<NoticeDraft | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const reset = useCallback(() => {
    setStep("keyword");
    setKeywords([]);
    setGenError(null);
    setDraft(null);
    setTitle("");
    setBody("");
  }, []);

  const handleAddKeyword = useCallback((raw: string): boolean => {
    const result = addKeyword(keywords, raw);
    if (!result.ok) {
      setGenError(ADD_REASON[result.reason]);
      return false;
    }
    setKeywords(result.keywords);
    setGenError(null);
    return true;
  }, [keywords]);

  async function handleGenerate() {
    if (!canGenerate(keywords)) {
      setGenError("키워드를 1개 이상 입력하세요.");
      return;
    }
    setStep("drafting");
    setGenError(null);
    try {
      const generated = await createNoticeDraft(keywords);
      setDraft(generated);
      setTitle(generated.title);
      setBody(generated.body);
      setStep("review");
    } catch (err) {
      setStep("keyword");
      if (err instanceof ApiError && err.status === 422) {
        setGenError(err.message); // 근거 문서 없음 — 문서 업로드 후 재시도
      } else if (err instanceof ApiError && err.status === 503) {
        setGenError("AI 초안 생성을 일시적으로 할 수 없습니다. 잠시 후 다시 시도하세요.");
      } else {
        setGenError(errorMessage(err));
      }
    }
  }

  async function handlePublish() {
    if (!draft || publishing) return;
    setPublishing(true);
    try {
      await publishNotice({ draftId: draft.draftId, title: title.trim(), body: body.trim() });
      setDialogOpen(false);
      showToast("공지를 발송했습니다. 입주민에게 알림이 전달됩니다.");
      reset();
    } catch (err) {
      setDialogOpen(false);
      if (err instanceof ApiError && err.status === 409) {
        showToast("이미 처리된 초안입니다. 다시 작성해 주세요.", "danger");
        reset();
      } else {
        showToast(errorMessage(err), "danger");
      }
    } finally {
      setPublishing(false);
    }
  }

  const curIdx = ORDER.indexOf(step);
  const canSend = title.trim().length > 0 && body.trim().length > 0;

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title nc-title">
          공지 초안 작성
        </h1>
        <ol className="nc-stepper">
          {ORDER.map((id, i) => {
            const done = i < curIdx;
            const current = i === curIdx;
            return (
              <li key={id} className="nc-stepper__item">
                <span
                  className="nc-stepper__dot"
                  data-state={done ? "done" : current ? "current" : "todo"}
                  aria-hidden="true"
                >
                  {done ? "✓" : i + 1}
                </span>
                <span className="nc-stepper__label" data-current={current || undefined}>
                  {STEP_LABELS[id]}
                </span>
                {i < ORDER.length - 1 ? <span className="nc-stepper__line" aria-hidden="true" /> : null}
              </li>
            );
          })}
        </ol>
      </header>

      <main className="admin-page__main">
        {step === "keyword" ? (
          <KeywordStep
            keywords={keywords}
            error={genError}
            onAdd={handleAddKeyword}
            onRemove={(i) => setKeywords((prev) => removeKeyword(prev, i))}
            onGenerate={handleGenerate}
          />
        ) : null}
        {step === "drafting" ? <DraftingStep /> : null}
        {step === "review" && draft ? (
          <ReviewStep
            draft={draft}
            title={title}
            body={body}
            canSend={canSend}
            onTitle={setTitle}
            onBody={setBody}
            onSend={() => setDialogOpen(true)}
            onBack={reset}
          />
        ) : null}
      </main>

      <Dialog
        open={dialogOpen}
        title="공지를 발송할까요?"
        description="검수를 완료했습니까? 발송 즉시 입주민에게 알림이 갑니다. 발송 후에는 수정할 수 없습니다."
        confirmLabel={publishing ? "발송 중…" : "발송 확인"}
        onCancel={() => setDialogOpen(false)}
        onConfirm={handlePublish}
      />

      {toast ? (
        <div className="nc-toast">
          <Toast tone={toast.tone} message={toast.message} />
        </div>
      ) : null}
    </>
  );
}

interface KeywordStepProps {
  keywords: readonly string[];
  error: string | null;
  onAdd: (raw: string) => boolean;
  onRemove: (index: number) => void;
  onGenerate: () => void;
}

function KeywordStep({ keywords, error, onAdd, onRemove, onGenerate }: KeywordStepProps) {
  const [input, setInput] = useState("");

  function commit() {
    if (onAdd(input)) setInput("");
  }

  return (
    <div className="nc-card nc-card--narrow">
      <h2 className="nc-card__title">무엇을 공지할까요?</h2>
      <p className="nc-card__lede">
        키워드를 입력하면 AI가 등록된 문서를 근거로 초안을 작성합니다. 작성된 초안은{" "}
        <strong>반드시 검수 후 발송</strong>되며 자동으로 전송되지 않습니다.
      </p>

      <div className="nc-field">
        <label htmlFor="nc-kw">키워드 (1~{MAX_KEYWORDS}개)</label>
        <div className="nc-chipinput">
          {keywords.map((kw, i) => (
            <span key={kw} className="nc-chip">
              {kw}
              <button
                type="button"
                className="nc-chip__remove"
                aria-label={`${kw} 제거`}
                onClick={() => onRemove(i)}
              >
                ×
              </button>
            </span>
          ))}
          <input
            id="nc-kw"
            type="text"
            className="nc-chipinput__field"
            value={input}
            placeholder={keywords.length === 0 ? "예: 단수, 배관 교체" : "키워드 추가"}
            aria-describedby="nc-kw-help"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                commit();
              } else if (e.key === "Backspace" && input === "" && keywords.length > 0) {
                onRemove(keywords.length - 1);
              }
            }}
          />
        </div>
        <div id="nc-kw-help" className="nc-field__help">
          Enter 또는 쉼표로 키워드를 추가하세요.
        </div>
        {error ? (
          <p className="nc-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>

      <Button
        type="button"
        variant="primary"
        className="nc-generate"
        disabled={!canGenerate(keywords)}
        onClick={onGenerate}
      >
        <span aria-hidden="true">✨</span> AI 초안 생성
      </Button>
    </div>
  );
}

function DraftingStep() {
  return (
    <div className="nc-card nc-card--narrow">
      <div className="nc-drafting" role="status" aria-live="polite">
        <span className="nc-drafting__mark" aria-hidden="true">
          L
        </span>
        <div className="nc-drafting__text">
          AI가 초안을 작성하고 있어요
          <span className="nc-caret" aria-hidden="true" />
        </div>
      </div>
      <Skeleton height="20px" width="70%" style={{ marginBottom: "var(--space-4)" }} />
      <Skeleton height="14px" width="100%" style={{ marginBottom: "var(--space-2)" }} />
      <Skeleton height="14px" width="96%" style={{ marginBottom: "var(--space-2)" }} />
      <Skeleton height="14px" width="88%" style={{ marginBottom: "var(--space-6)" }} />
      <Skeleton height="14px" width="60%" />
    </div>
  );
}

interface ReviewStepProps {
  draft: NoticeDraft;
  title: string;
  body: string;
  canSend: boolean;
  onTitle: (value: string) => void;
  onBody: (value: string) => void;
  onSend: () => void;
  onBack: () => void;
}

function ReviewStep({ draft, title, body, canSend, onTitle, onBody, onSend, onBack }: ReviewStepProps) {
  return (
    <div className="nc-review">
      <div className="nc-card nc-editor">
        <div className="nc-editor__head">
          <span className="nc-badge">
            <span aria-hidden="true">✨</span> AI 초안 · 검토 후 발송하세요
          </span>
          <ConfidenceBadge status={confidenceStatus(draft.confidence)} />
        </div>

        <div className="nc-field">
          <label htmlFor="nc-title">제목</label>
          <input
            id="nc-title"
            type="text"
            className="nc-editor__title"
            value={title}
            onChange={(e) => onTitle(e.target.value)}
          />
        </div>

        <div className="nc-field">
          <label htmlFor="nc-body">본문</label>
          <textarea
            id="nc-body"
            rows={13}
            className="nc-editor__body"
            value={body}
            onChange={(e) => onBody(e.target.value)}
          />
        </div>

        <p className="nc-mask">
          <span aria-hidden="true">🔒</span> 본문에 입력된 개인정보(이름·연락처)는 발송 시 자동
          마스킹됩니다.
        </p>
      </div>

      <aside className="nc-side">
        <div className="nc-card">
          <h3 className="nc-side__title">근거 문서</h3>
          <div className="nc-citations">
            {draft.citations.map((c) => (
              <CitationCard key={c.chunkId} title={c.documentTitle} meta={c.quote} href="#" />
            ))}
          </div>
        </div>

        <div className="nc-side__actions">
          <Button variant="primary" disabled={!canSend} onClick={onSend}>
            검수 완료 · 발송하기
          </Button>
          <button type="button" className="nc-back" onClick={onBack}>
            ← 키워드 다시 입력
          </button>
        </div>
      </aside>
    </div>
  );
}
