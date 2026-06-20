import { cx } from "../../lib/cx";

export type StatusKind = "received" | "progress" | "done" | "fault";

export interface StatusPillProps {
  status: StatusKind;
  label?: string;
  className?: string;
}

const LABEL: Record<StatusKind, string> = {
  received: "접수됨",
  progress: "처리중",
  done: "완료",
  fault: "장애",
};

/** 민원·시설 상태 표시. 색 = semantic, 점 + 텍스트 병기. */
export function StatusPill({ status, label, className }: StatusPillProps) {
  return (
    <span className={cx("status-pill", `status-pill--${status}`, className)}>
      <span className="status-pill__dot" aria-hidden="true" />
      {label ?? LABEL[status]}
    </span>
  );
}
