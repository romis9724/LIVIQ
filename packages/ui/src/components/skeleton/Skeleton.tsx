import type { CSSProperties } from "react";
import { cx } from "../../lib/cx";

export interface SkeletonProps {
  width?: string;
  height?: string;
  radius?: string;
  className?: string;
  style?: CSSProperties;
}

/** 로딩 자리표시자(shimmer). prefers-reduced-motion 에서 애니메이션이 멈춘다. */
export function Skeleton({ width, height, radius, className, style }: SkeletonProps) {
  return (
    <div
      className={cx("skeleton", className)}
      aria-hidden="true"
      style={{ width, height, borderRadius: radius, ...style }}
    />
  );
}
