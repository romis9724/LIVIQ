"use client";

import { useEffect, useId, useRef } from "react";

export interface DialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 위험 액션 여부 — confirm 버튼을 danger 변형으로 표시. */
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * 위험 액션 확인 다이얼로그(예: 공지 발송). Escape·백드롭으로 취소, 열릴 때 포커스 이동.
 */
export function Dialog({
  open,
  title,
  description,
  confirmLabel = "확인",
  cancelLabel = "취소",
  danger = false,
  onConfirm,
  onCancel,
}: DialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    if (!open) return;
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="dialog-backdrop" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog__title" id={titleId}>
          {title}
        </div>
        {description ? (
          <div className="dialog__desc" id={descId}>
            {description}
          </div>
        ) : null}
        <div className="dialog__actions">
          <button type="button" className="btn btn--secondary btn--sm" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={danger ? "btn btn--danger btn--sm" : "btn btn--primary btn--sm"}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
