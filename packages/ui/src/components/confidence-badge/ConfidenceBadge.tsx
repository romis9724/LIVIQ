import { cx } from "../../lib/cx";

export type ConfidenceStatus = "answered" | "review" | "handoff";

export interface ConfidenceBadgeProps {
  status: ConfidenceStatus;
  /** 라벨 재정의 (기본 문구는 status별 제공). */
  label?: string;
  className?: string;
}

const PRESET: Record<ConfidenceStatus, { glyph: string; label: string }> = {
  answered: { glyph: "✓", label: "답변됨 · 신뢰도 높음" },
  review: { glyph: "!", label: "검토 필요" },
  handoff: { glyph: "☎", label: "담당자 연결" },
};

/**
 * 신뢰도/응답 상태 배지. 색만으로 전달하지 않도록 아이콘 + 텍스트를 함께 쓴다.
 */
export function ConfidenceBadge({ status, label, className }: ConfidenceBadgeProps) {
  const preset = PRESET[status];
  return (
    <span className={cx("confidence-badge", `confidence-badge--${status}`, className)}>
      <span className="confidence-badge__glyph" aria-hidden="true">
        {preset.glyph}
      </span>
      {label ?? preset.label}
    </span>
  );
}
