"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Dialog, FileDropzone, SurfaceCard } from "@liviq/ui";
import {
  FEE_ITEMS,
  HOUSEHOLDS,
  PREV_MONTH_TOTAL,
  feeSummary,
  formatWon,
  monthLabel,
  percentDelta,
  previewRows,
  validateUpload,
  type ValidationResult,
} from "./logic";

type Step = "select" | "validate" | "preview" | "confirm";

const STEP_LABELS: Record<Step, string> = {
  select: "파일 선택",
  validate: "검증",
  preview: "미리보기",
  confirm: "확정",
};
const ORDER: Step[] = ["select", "validate", "preview", "confirm"];

const UPLOAD_MONTHS = ["2026-07", "2026-08"] as const;
const VALIDATE_DELAY_MS = 1200;

interface UploadWizardProps {
  onViewStatus: () => void;
}

export function UploadWizard({ onViewStatus }: UploadWizardProps) {
  const [step, setStep] = useState<Step>("select");
  const [targetMonth, setTargetMonth] = useState<string>(UPLOAD_MONTHS[0]);
  const [fileName, setFileName] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const startValidation = () => {
    if (!fileName) return;
    setStep("validate");
    setValidating(true);
    setResult(null);
    timer.current = setTimeout(() => {
      setResult(validateUpload(fileName));
      setValidating(false);
    }, VALIDATE_DELAY_MS);
  };

  const reset = () => {
    setStep("select");
    setFileName(null);
    setValidating(false);
    setResult(null);
    setDone(false);
  };

  const curIdx = ORDER.indexOf(step);

  return (
    <>
      <ol className="fu-stepper" aria-label="업로드 단계">
        {ORDER.map((id, i) => {
          const isDone = i < curIdx;
          const current = i === curIdx;
          return (
            <li key={id} className="fu-stepper__item">
              <span
                className="fu-stepper__dot"
                data-state={isDone ? "done" : current ? "current" : "todo"}
                aria-hidden="true"
              >
                {isDone ? "✓" : i + 1}
              </span>
              <span className="fu-stepper__label" data-current={current || undefined}>
                {STEP_LABELS[id]}
              </span>
              {i < ORDER.length - 1 ? (
                <span className="fu-stepper__line" aria-hidden="true" />
              ) : null}
            </li>
          );
        })}
      </ol>

      {step === "select" ? (
        <SelectStep
          targetMonth={targetMonth}
          onMonth={setTargetMonth}
          fileName={fileName}
          onFile={(f) => setFileName(f.name)}
          onNext={startValidation}
        />
      ) : null}

      {step === "validate" ? (
        <ValidateStep
          validating={validating}
          result={result}
          onBack={() => setStep("select")}
          onNext={() => setStep("preview")}
        />
      ) : null}

      {step === "preview" ? (
        <PreviewStep onBack={() => setStep("validate")} onNext={() => setStep("confirm")} />
      ) : null}

      {step === "confirm" ? (
        done ? (
          <DoneScreen month={targetMonth} onReset={reset} onViewStatus={onViewStatus} />
        ) : (
          <ConfirmStep
            month={targetMonth}
            onBack={() => setStep("preview")}
            onConfirm={() => setDialogOpen(true)}
          />
        )
      ) : null}

      <Dialog
        open={dialogOpen}
        danger
        title={`${monthLabel(targetMonth)} 관리비를 확정할까요?`}
        description={`${monthLabel(targetMonth)} 관리비를 ${HOUSEHOLDS.length}세대에 반영합니다. 같은 달 기존 데이터는 전체 교체되며 되돌릴 수 없습니다.`}
        confirmLabel="전체 교체 · 확정"
        onCancel={() => setDialogOpen(false)}
        onConfirm={() => {
          setDialogOpen(false);
          setDone(true);
        }}
      />
    </>
  );
}

interface SelectStepProps {
  targetMonth: string;
  onMonth: (m: string) => void;
  fileName: string | null;
  onFile: (file: File) => void;
  onNext: () => void;
}

function SelectStep({ targetMonth, onMonth, fileName, onFile, onNext }: SelectStepProps) {
  return (
    <section className="fu-card" aria-labelledby="fu-select-title">
      <h2 id="fu-select-title" className="fu-card__title">
        관리비 엑셀 업로드
      </h2>
      <p className="fu-card__lede">
        관리비는 <strong>업로드한 엑셀이 단일 출처</strong>입니다. 대상 월과 파일을 선택하세요.
      </p>

      <div className="fu-field">
        <label htmlFor="fu-month">대상 월</label>
        <select id="fu-month" value={targetMonth} onChange={(e) => onMonth(e.target.value)}>
          {UPLOAD_MONTHS.map((m) => (
            <option key={m} value={m}>
              {monthLabel(m)}
            </option>
          ))}
        </select>
      </div>

      <FileDropzone
        label="관리비 엑셀 업로드"
        accept=".xlsx"
        maxSizeMb={10}
        state={fileName ? "selected" : "idle"}
        fileName={fileName ?? undefined}
        onFile={onFile}
      />

      <p className="fu-hint">
        <button type="button" className="fu-templink">
          템플릿 다운로드
        </button>
        <span>컬럼: 동 · 호 · 항목별 금액(원 단위)</span>
      </p>

      <div className="fu-actions">
        <Button variant="primary" onClick={onNext} disabled={!fileName}>
          다음 · 검증
        </Button>
      </div>
    </section>
  );
}

interface ValidateStepProps {
  validating: boolean;
  result: ValidationResult | null;
  onBack: () => void;
  onNext: () => void;
}

function ValidateStep({ validating, result, onBack, onNext }: ValidateStepProps) {
  if (validating || !result) {
    return (
      <section className="fu-card">
        <div className="fu-progress" role="status" aria-live="polite">
          <span className="fu-spinner" aria-hidden="true" />
          엑셀을 검증하고 있어요…
        </div>
      </section>
    );
  }

  if (!result.ok) {
    return (
      <section className="fu-card" aria-labelledby="fu-err-title">
        <h2 id="fu-err-title" className="fu-card__title">
          <span className="fu-badge fu-badge--err">
            <span aria-hidden="true">⚠</span> 검증 실패
          </span>
        </h2>
        <p className="fu-errnote" role="alert">
          오류 {result.issues.length}건 · 누락 세대 {result.missingCount}건. 오류를 수정한 뒤 다시
          업로드하세요.
        </p>

        <div className="surface-card fu-tablecard">
          <table className="fu-table">
            <thead>
              <tr>
                <th scope="col" className="fu-num">
                  행
                </th>
                <th scope="col">컬럼</th>
                <th scope="col">사유</th>
              </tr>
            </thead>
            <tbody>
              {result.issues.map((issue) => (
                <tr key={`${issue.row}-${issue.column}`}>
                  <td className="fu-num">{issue.row}</td>
                  <td>{issue.column}</td>
                  <td>{issue.reason}</td>
                </tr>
              ))}
              <tr>
                <td className="fu-num">—</td>
                <td>세대</td>
                <td>누락 세대 {result.missingCount}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="fu-actions">
          <Button variant="secondary" onClick={onBack}>
            ← 이전으로
          </Button>
        </div>
      </section>
    );
  }

  return (
    <section className="fu-card">
      <span className="fu-badge fu-badge--ok">
        <span aria-hidden="true">✓</span> {result.validatedCount}세대 검증 통과
      </span>
      <p className="fu-card__lede" style={{ marginTop: "var(--space-4)" }}>
        누락·중복·음수 금액 없이 모든 세대가 통과했습니다.
      </p>
      <div className="fu-actions fu-actions--between">
        <Button variant="secondary" onClick={onBack}>
          ← 이전
        </Button>
        <Button variant="primary" onClick={onNext}>
          다음 · 미리보기
        </Button>
      </div>
    </section>
  );
}

function PreviewStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const summary = feeSummary(HOUSEHOLDS);
  const delta = percentDelta(summary.total, PREV_MONTH_TOTAL);
  const rows = previewRows(HOUSEHOLDS);
  const rest = HOUSEHOLDS.length - rows.length;
  const mainItems = FEE_ITEMS.slice(0, 2);

  return (
    <section aria-labelledby="fu-preview-title">
      <h2 id="fu-preview-title" className="fu-section__title">
        반영 전 미리보기
      </h2>

      <div className="fu-stats">
        <SurfaceCard className="fu-stat">
          <div className="fu-stat__label">합계</div>
          <div className="fu-stat__value">{formatWon(summary.total)}</div>
        </SurfaceCard>
        <SurfaceCard className="fu-stat">
          <div className="fu-stat__label">세대 평균</div>
          <div className="fu-stat__value">{formatWon(summary.average)}</div>
        </SurfaceCard>
        <SurfaceCard className="fu-stat">
          <div className="fu-stat__label">전월 대비</div>
          <div className={`fu-stat__value fu-stat__delta ${delta >= 0 ? "fu-stat__delta--up" : "fu-stat__delta--down"}`}>
            {delta >= 0 ? "+" : ""}
            {delta}%
          </div>
        </SurfaceCard>
      </div>

      <div className="surface-card fu-tablecard">
        <table className="fu-table">
          <thead>
            <tr>
              <th scope="col">동</th>
              <th scope="col">호</th>
              {mainItems.map((it) => (
                <th scope="col" key={it.key} className="fu-num">
                  {it.label}
                </th>
              ))}
              <th scope="col" className="fu-num">
                합계
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr key={`${h.dong}-${h.ho}`}>
                <td>{h.dong}</td>
                <td>{h.ho}</td>
                {mainItems.map((it) => (
                  <td key={it.key} className="fu-num">
                    {formatWon(h.items[it.key])}
                  </td>
                ))}
                <td className="fu-num">{formatWon(h.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="fu-table__more">…외 {rest}세대</div>
      </div>

      <div className="fu-actions fu-actions--between">
        <Button variant="secondary" onClick={onBack}>
          ← 이전
        </Button>
        <Button variant="primary" onClick={onNext}>
          다음 · 확정
        </Button>
      </div>
    </section>
  );
}

interface ConfirmStepProps {
  month: string;
  onBack: () => void;
  onConfirm: () => void;
}

function ConfirmStep({ month, onBack, onConfirm }: ConfirmStepProps) {
  return (
    <section className="fu-card" aria-labelledby="fu-confirm-title">
      <h2 id="fu-confirm-title" className="fu-card__title">
        {monthLabel(month)} 관리비 확정
      </h2>
      <p className="fu-card__lede">
        확정하면 {monthLabel(month)} 관리비가 {HOUSEHOLDS.length}세대에 반영됩니다.
      </p>
      <p className="fu-errnote">
        같은 달 기존 데이터는 <strong>전체 교체</strong>되며 되돌릴 수 없습니다. 확정 전에 미리보기를
        다시 확인하세요.
      </p>
      <div className="fu-actions fu-actions--between">
        <Button variant="secondary" onClick={onBack}>
          ← 이전
        </Button>
        <Button variant="danger" onClick={onConfirm}>
          확정하기
        </Button>
      </div>
    </section>
  );
}

interface DoneScreenProps {
  month: string;
  onReset: () => void;
  onViewStatus: () => void;
}

function DoneScreen({ month, onReset, onViewStatus }: DoneScreenProps) {
  return (
    <section className="fu-card">
      <div className="fu-done">
        <div className="fu-done__mark" aria-hidden="true">
          ✓
        </div>
        <div className="fu-done__title">{monthLabel(month)} 관리비가 반영되었습니다</div>
        <p className="fu-done__lede">
          {HOUSEHOLDS.length}세대에 전체 교체로 반영되었습니다. 부과 현황에서 세대별 내역을 확인하세요.
        </p>
        <div className="fu-actions" style={{ justifyContent: "center" }}>
          <Button variant="primary" onClick={onViewStatus}>
            부과 현황 보기
          </Button>
          <Button variant="secondary" onClick={onReset}>
            새 업로드
          </Button>
        </div>
      </div>
    </section>
  );
}
