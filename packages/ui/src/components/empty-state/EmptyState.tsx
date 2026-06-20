import type { ReactNode } from "react";
import { cx } from "../../lib/cx";

export interface EmptyStateProps {
  /** 이모지/아이콘 (장식용). */
  icon?: string;
  title: string;
  description?: string;
  /** 행동 유도 영역 (버튼 등). */
  action?: ReactNode;
  className?: string;
}

/** 빈 목록 안내 — 단순 공백이 아니라 다음 행동을 유도한다. */
export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cx("empty-state", className)}>
      {icon ? (
        <div className="empty-state__icon" aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <div className="empty-state__title">{title}</div>
      {description ? <div className="empty-state__desc">{description}</div> : null}
      {action ? <div className="empty-state__action">{action}</div> : null}
    </div>
  );
}
