import type { ReactNode } from "react";
import { cx } from "../../lib/cx";

export type StatTone = "default" | "success" | "warning" | "danger";

export interface StatCardProps {
  /** 위쪽 라벨(--text-sm, muted). */
  label: string;
  /** 아래쪽 값(--text-2xl/700, tabular-nums). */
  value: ReactNode;
  /** 값 뒤 단위(건·원·% 등). */
  unit?: string;
  /** 상태 강조 — 값 색만 바뀐다(배경·테두리 칠 금지, docs/05 §5A). */
  tone?: StatTone;
  className?: string;
}

/** 관리 화면 현황 카드 — 라벨 위·값 아래 단일 패턴(docs/05 §5A). */
export function StatCard({ label, value, unit, tone = "default", className }: StatCardProps) {
  return (
    <div className={cx("stat-card", className)}>
      <div className="stat-card__label">{label}</div>
      <div className={cx("stat-card__value", tone !== "default" && `stat-card__value--${tone}`)}>
        {value}
        {unit ? <span className="stat-card__unit">{unit}</span> : null}
      </div>
    </div>
  );
}

export interface StatGridProps {
  children: ReactNode;
  className?: string;
}

/** StatCard 배치용 한 행 grid — `auto-fit minmax(9rem, 1fr)`. */
export function StatGrid({ children, className }: StatGridProps) {
  return <div className={cx("stat-grid", className)}>{children}</div>;
}
