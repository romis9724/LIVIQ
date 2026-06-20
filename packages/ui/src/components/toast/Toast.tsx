import { cx } from "../../lib/cx";

export type ToastTone = "success" | "danger" | "neutral";

export interface ToastProps {
  message: string;
  tone?: ToastTone;
  className?: string;
}

const GLYPH: Record<ToastTone, string | null> = {
  success: "✓",
  danger: "!",
  neutral: null,
};

/** 일시적 피드백 알림. aria-live=polite 로 스크린리더에 전달된다. */
export function Toast({ message, tone = "success", className }: ToastProps) {
  const glyph = GLYPH[tone];
  return (
    <div className={cx("toast", `toast--${tone}`, className)} role="status" aria-live="polite">
      {glyph ? (
        <span className="toast__icon" aria-hidden="true">
          {glyph}
        </span>
      ) : null}
      <span>{message}</span>
    </div>
  );
}
