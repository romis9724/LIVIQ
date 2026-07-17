"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Dialog, FileDropzone, SurfaceCard, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  applyFeeUpload,
  uploadFeeExcel,
  type FeeUploadResult,
} from "@/lib/api";
import { breakdownColumns, formatWon, monthLabel, unitLabel } from "./logic";

type Step = "select" | "review" | "confirm";

const STEP_LABELS: Record<Step, string> = {
  select: "파일 선택",
  review: "검증·미리보기",
  confirm: "확정",
};
const ORDER: Step[] = ["select", "review", "confirm"];
const TOAST_DURATION_MS = 3200;

/** 이번 달(YYYY-MM). 업로드 대상 월 기본값. */
function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

interface UploadWizardProps {
  onApplied: () => void;
}

export function UploadWizard({ onApplied }: UploadWizardProps) {
  const [period, setPeriod] = useState<string>(currentMonth());
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState<FeeUploadResult | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [toast, setToast] = useState<{ message: string; tone: ToastTone } | null>(null);
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

  const step: Step = result ? "review" : "select";
  const curIdx = ORDER.indexOf(step);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setResult(null);
    try {
      const res = await uploadFeeExcel(file, period);
      setResult(res);
      if (res.status === "failed") {
        showToast(`검증 실패 — 유효한 세대가 없습니다.`, "danger");
      }
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setUploading(false);
    }
  }

  async function handleApply() {
    if (!result) return;
    setDialogOpen(false);
    setApplying(true);
    try {
      const applied = await applyFeeUpload(result.uploadId);
      showToast(`${monthLabel(period)} 관리비를 ${applied.applied}세대에 반영했습니다.`);
      reset();
      onApplied();
    } catch (err) {
      // 409=validated 아님(이미 적용/실패) 등 상태코드 메시지 노출.
      showToast(errorMessage(err), "danger");
    } finally {
      setApplying(false);
    }
  }

  function reset() {
    setResult(null);
    setFile(null);
  }

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

      {result ? (
        <ReviewStep
          result={result}
          period={period}
          applying={applying}
          onBack={reset}
          onApply={() => setDialogOpen(true)}
        />
      ) : (
        <SelectStep
          period={period}
          onPeriod={setPeriod}
          file={file}
          uploading={uploading}
          onFile={setFile}
          onNext={handleUpload}
        />
      )}

      <Dialog
        open={dialogOpen}
        danger
        title={`${monthLabel(period)} 관리비를 확정할까요?`}
        description={`${monthLabel(period)} 관리비를 ${result?.validRows ?? 0}세대에 반영합니다. 같은 달 기존 데이터는 전체 교체되며 되돌릴 수 없습니다.`}
        confirmLabel="전체 교체 · 확정"
        onCancel={() => setDialogOpen(false)}
        onConfirm={handleApply}
      />

      {toast ? (
        <div className="fu-toast-slot">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </>
  );
}

interface SelectStepProps {
  period: string;
  onPeriod: (m: string) => void;
  file: File | null;
  uploading: boolean;
  onFile: (file: File) => void;
  onNext: () => void;
}

function SelectStep({ period, onPeriod, file, uploading, onFile, onNext }: SelectStepProps) {
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
        <input
          id="fu-month"
          type="month"
          value={period}
          onChange={(e) => onPeriod(e.target.value)}
        />
      </div>

      <FileDropzone
        label="관리비 엑셀 업로드"
        accept=".xlsx"
        maxSizeMb={10}
        state={uploading ? "uploading" : file ? "selected" : "idle"}
        fileName={file?.name}
        onFile={onFile}
      />

      <p className="fu-hint">
        <span>컬럼: 동 · 층 · 호 · 항목별 금액(원 단위)</span>
      </p>

      <div className="fu-actions">
        <Button variant="primary" onClick={onNext} disabled={!file || uploading}>
          {uploading ? "검증 중…" : "다음 · 검증"}
        </Button>
      </div>
    </section>
  );
}

interface ReviewStepProps {
  result: FeeUploadResult;
  period: string;
  applying: boolean;
  onBack: () => void;
  onApply: () => void;
}

function ReviewStep({ result, period, applying, onBack, onApply }: ReviewStepProps) {
  const failed = result.status === "failed";
  const hasErrors = result.errors.length > 0;
  const columns = breakdownColumns(result.preview);

  return (
    <section aria-labelledby="fu-review-title">
      <h2 id="fu-review-title" className="fu-section__title">
        {monthLabel(period)} 검증 결과
      </h2>

      <div className="fu-stats">
        <SurfaceCard className="fu-stat">
          <div className="fu-stat__label">유효 세대</div>
          <div className="fu-stat__value">{result.validRows}세대</div>
        </SurfaceCard>
        <SurfaceCard className="fu-stat">
          <div className="fu-stat__label">파싱 행</div>
          <div className="fu-stat__value">{result.rowCount}행</div>
        </SurfaceCard>
        <SurfaceCard className="fu-stat">
          <div className="fu-stat__label">오류</div>
          <div
            className={`fu-stat__value ${hasErrors ? "fu-stat__delta--up" : ""}`}
          >
            {result.errors.length}건
          </div>
        </SurfaceCard>
      </div>

      {failed ? (
        <p className="fu-errnote" role="alert">
          유효한 세대가 없어 확정할 수 없습니다. 오류를 수정한 뒤 다시 업로드하세요.
        </p>
      ) : hasErrors ? (
        <p className="fu-errnote">
          오류 {result.errors.length}행은 확정 시 <strong>스킵</strong>되고 유효한{" "}
          {result.validRows}세대만 반영됩니다.
        </p>
      ) : null}

      {hasErrors ? (
        <div className="surface-card fu-tablecard">
          <table className="fu-table">
            <thead>
              <tr>
                <th scope="col" className="fu-num">
                  행
                </th>
                <th scope="col">사유</th>
              </tr>
            </thead>
            <tbody>
              {result.errors.map((e) => (
                <tr key={`${e.row}-${e.reason}`}>
                  <td className="fu-num">{e.row}</td>
                  <td>{e.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {result.preview.length > 0 ? (
        <div className="surface-card fu-tablecard">
          <table className="fu-table">
            <thead>
              <tr>
                <th scope="col">동</th>
                <th scope="col">호</th>
                {columns.map((c) => (
                  <th scope="col" key={c} className="fu-num">
                    {c}
                  </th>
                ))}
                <th scope="col" className="fu-num">
                  합계
                </th>
              </tr>
            </thead>
            <tbody>
              {result.preview.map((row) => (
                <tr key={`${row.buildingName}-${row.floor}-${row.unitNo}`}>
                  <td>{row.buildingName}</td>
                  <td>{unitLabel(row.floor, row.unitNo)}</td>
                  {columns.map((c) => (
                    <td key={c} className="fu-num">
                      {row.breakdown[c] != null ? formatWon(row.breakdown[c]) : "—"}
                    </td>
                  ))}
                  <td className="fu-num">{formatWon(row.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.validRows > result.preview.length ? (
            <div className="fu-table__more">…외 {result.validRows - result.preview.length}세대</div>
          ) : null}
        </div>
      ) : null}

      <div className="fu-actions fu-actions--between">
        <Button variant="secondary" onClick={onBack}>
          ← 다시 업로드
        </Button>
        {!failed ? (
          <Button variant="danger" onClick={onApply} disabled={applying}>
            {applying ? "반영 중…" : "확정 적용"}
          </Button>
        ) : null}
      </div>
    </section>
  );
}
