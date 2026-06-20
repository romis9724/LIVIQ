"use client";

import { cx } from "../../lib/cx";

export interface SwitchProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** 접근성 라벨 (시각 라벨이 별도로 있을 때도 필수). */
  label: string;
  className?: string;
}

/** 접근성 토글 스위치 — role=switch, aria-checked. */
export function Switch({ checked, onChange, label, className }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={cx("switch", checked && "switch--on", className)}
      onClick={() => onChange(!checked)}
    >
      <span className="switch__knob" aria-hidden="true" />
    </button>
  );
}
