"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Dialog, Skeleton, Toast } from "@liviq/ui";
import "./notice-composer.css";

type Step = "keyword" | "drafting" | "review";

const STEP_LABELS: Record<Step, string> = {
  keyword: "키워드",
  drafting: "AI 초안",
  review: "검수",
};
const ORDER: Step[] = ["keyword", "drafting", "review"];

const DRAFT_BODY = `안녕하세요, 래미안 한강 1단지 관리사무소입니다.

노후 배관 교체 공사로 인해 아래와 같이 단수가 예정되어 있어 안내드립니다.

· 일시: 2026년 6월 22일(월) 03:00 ~ 05:00 (약 2시간)
· 대상: 1203동 전 세대
· 유의사항: 단수 시간 동안 수돗물 사용이 어려우니 미리 받아두시기 바랍니다.

공사 진행 상황에 따라 종료 시각이 다소 변동될 수 있습니다. 입주민 여러분의 양해를 부탁드립니다.

문의: 관리사무소 (대표번호 안내 참고)`;

export function NoticeComposer() {
  const [step, setStep] = useState<Step>("keyword");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const generate = () => {
    setStep("drafting");
    timer.current = setTimeout(() => setStep("review"), 1400);
  };

  const curIdx = ORDER.indexOf(step);

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
        {step === "keyword" ? <KeywordStep onGenerate={generate} /> : null}
        {step === "drafting" ? <DraftingStep /> : null}
        {step === "review" ? (
          <ReviewStep onSend={() => setDialogOpen(true)} onBack={() => setStep("keyword")} />
        ) : null}
      </main>

      <Dialog
        open={dialogOpen}
        title="공지를 발송할까요?"
        description="[중요] 6/22(월) 새벽 단수 안내 · 대상 1,204세대 · 검수 완료. 발송 후에는 수정할 수 없으며 입주민 앱·푸시로 즉시 전달됩니다."
        confirmLabel="발송 확인"
        onCancel={() => setDialogOpen(false)}
        onConfirm={() => {
          setDialogOpen(false);
          setSent(true);
        }}
      />

      {sent ? (
        <div className="nc-toast">
          <Toast tone="success" message="공지가 1,204세대 입주민에게 발송되었습니다." />
        </div>
      ) : null}
    </>
  );
}

function KeywordStep({ onGenerate }: { onGenerate: () => void }) {
  return (
    <div className="nc-card nc-card--narrow">
      <h2 className="nc-card__title">무엇을 공지할까요?</h2>
      <p className="nc-card__lede">
        키워드와 핵심 정보를 입력하면 AI가 초안을 작성합니다. 작성된 초안은{" "}
        <strong>반드시 검수 후 발송</strong>되며 자동으로 전송되지 않습니다.
      </p>

      <form
        className="nc-form"
        onSubmit={(e) => {
          e.preventDefault();
          onGenerate();
        }}
      >
        <div className="nc-field">
          <label htmlFor="nc-kw">키워드</label>
          <input
            id="nc-kw"
            type="text"
            defaultValue="단수, 배관 교체, 1203동"
            aria-describedby="nc-kw-help"
          />
          <div id="nc-kw-help" className="nc-field__help">
            쉼표로 구분해 여러 키워드를 입력하세요.
          </div>
        </div>

        <div className="nc-field-row">
          <div className="nc-field">
            <label htmlFor="nc-cat">말머리</label>
            <select id="nc-cat" defaultValue="중요">
              <option>중요</option>
              <option>생활</option>
              <option>공사</option>
              <option>행사</option>
            </select>
          </div>
          <div className="nc-field">
            <label htmlFor="nc-scope">대상 범위</label>
            <select id="nc-scope" defaultValue="1203동 전 세대">
              <option>1203동 전 세대</option>
              <option>단지 전체</option>
              <option>특정 라인</option>
            </select>
          </div>
        </div>

        <div className="nc-field">
          <label htmlFor="nc-info">핵심 정보 (일시·유의사항 등)</label>
          <textarea
            id="nc-info"
            rows={3}
            defaultValue="6/22(월) 03:00~05:00, 노후 배관 교체로 약 2시간 단수 예정"
          />
        </div>

        <Button type="submit" variant="primary" className="nc-generate">
          <span aria-hidden="true">✨</span> AI 초안 생성
        </Button>
      </form>
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

function ReviewStep({ onSend, onBack }: { onSend: () => void; onBack: () => void }) {
  return (
    <div className="nc-review">
      <div className="nc-card nc-editor">
        <span className="nc-badge">
          <span aria-hidden="true">✨</span> AI 초안 · 검토 후 발송하세요
        </span>

        <div className="nc-field">
          <label htmlFor="nc-title">제목</label>
          <input
            id="nc-title"
            type="text"
            className="nc-editor__title"
            defaultValue="[중요] 6/22(월) 새벽 단수 안내 — 노후 배관 교체 공사"
          />
        </div>

        <div className="nc-field">
          <label htmlFor="nc-body">본문</label>
          <textarea id="nc-body" rows={13} className="nc-editor__body" defaultValue={DRAFT_BODY} />
        </div>

        <p className="nc-mask">
          <span aria-hidden="true">🔒</span> 본문에 입력된 개인정보(이름·연락처)는 발송 시 자동
          마스킹됩니다.
        </p>
      </div>

      <aside className="nc-side">
        <div className="nc-card">
          <h3 className="nc-side__title">발송 전 검수</h3>
          <ul className="nc-check">
            <li>
              <span className="nc-check__ok" aria-hidden="true">
                ✓
              </span>
              <span>일시·대상 정보가 입력값과 일치</span>
            </li>
            <li>
              <span className="nc-check__ok" aria-hidden="true">
                ✓
              </span>
              <span>개인정보 마스킹 적용됨</span>
            </li>
            <li>
              <span className="nc-check__warn" aria-hidden="true">
                !
              </span>
              <span className="nc-check__muted">종료 시각 변동 가능 문구 확인 권장</span>
            </li>
          </ul>
          <div className="nc-target">
            <span>발송 대상</span>
            <span className="nc-target__count">1,204세대</span>
          </div>
        </div>

        <div className="nc-side__actions">
          <Button variant="primary" onClick={onSend}>
            검수 완료 · 발송하기
          </Button>
          <Button variant="secondary">임시저장</Button>
          <button type="button" className="nc-back" onClick={onBack}>
            ← 키워드 다시 입력
          </button>
        </div>
      </aside>
    </div>
  );
}
