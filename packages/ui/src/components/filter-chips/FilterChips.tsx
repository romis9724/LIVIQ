import { cx } from "../../lib/cx";

export interface FilterChipItem<T extends string = string> {
  id: T;
  label: string;
  /** 있으면 라벨 뒤에 건수 뱃지를 표시한다. */
  count?: number;
}

export interface FilterChipsProps<T extends string = string> {
  items: readonly FilterChipItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** tablist 접근성 이름 (예: "상태 필터"). */
  label: string;
  className?: string;
}

/** 목록 상태 필터 칩 — tablist·aria-selected·radius full(docs/05 §5A). */
export function FilterChips<T extends string = string>({
  items,
  value,
  onChange,
  label,
  className,
}: FilterChipsProps<T>) {
  return (
    <div className={cx("filter-chips", className)} role="tablist" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={item.id === value}
          className="filter-chip"
          onClick={() => onChange(item.id)}
        >
          {item.label}
          {item.count === undefined ? null : (
            <span className="filter-chip__count">{item.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}
