"use client";

interface TabGroupProps<T extends string> {
  label: string;
  className: string;
  tabClassName: string;
  options: readonly T[];
  labels: Record<T, string>;
  active: T;
  onSelect: (value: T) => void;
}

/** 세그먼트 탭 그룹(뷰·오버레이·스타일·현황 목록 공용) — role=tablist·aria-selected. */
export function TabGroup<T extends string>({
  label,
  className,
  tabClassName,
  options,
  labels,
  active,
  onSelect,
}: TabGroupProps<T>) {
  return (
    <div className={className} role="tablist" aria-label={label}>
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          role="tab"
          aria-selected={active === opt}
          className={tabClassName}
          data-active={active === opt || undefined}
          onClick={() => onSelect(opt)}
        >
          {labels[opt]}
        </button>
      ))}
    </div>
  );
}
