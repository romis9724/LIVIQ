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
  /** 값 아래 보조 액션(예: 관련 목록 열기 버튼). 링크·버튼 1개 수준으로. */
  action?: ReactNode;
  className?: string;
}

/** 관리 화면 현황 카드 — 라벨 위·값 아래 단일 패턴(docs/05 §5A). */
export function StatCard({
  label,
  value,
  unit,
  tone = "default",
  action,
  className,
}: StatCardProps) {
  const valueEl = (
    <div className={cx("stat-card__value", tone !== "default" && `stat-card__value--${tone}`)}>
      {value}
      {unit ? <span className="stat-card__unit">{unit}</span> : null}
    </div>
  );
  return (
    <div className={cx("stat-card", className)}>
      <div className="stat-card__label">{label}</div>
      {action ? (
        // 보조 액션은 값과 같은 라인 우측 정렬(사용자 지시).
        <div className="stat-card__row">
          {valueEl}
          <div className="stat-card__action">{action}</div>
        </div>
      ) : (
        valueEl
      )}
    </div>
  );
}

export interface StatGridProps {
  children: ReactNode;
  className?: string;
}

/** StatCard 배치용 grid — 한 줄 최대 5칸·빈 트랙 유지(auto-fill, docs/05 §5A). */
export function StatGrid({ children, className }: StatGridProps) {
  return <div className={cx("stat-grid", className)}>{children}</div>;
}
