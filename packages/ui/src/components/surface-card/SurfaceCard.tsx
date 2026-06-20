import type { ElementType, HTMLAttributes } from "react";
import { cx } from "../../lib/cx";

export interface SurfaceCardProps extends HTMLAttributes<HTMLElement> {
  /** 시맨틱 요소 지정 (기본 section). */
  as?: ElementType;
}

/** elevation 토큰을 쓰는 기본 정보 카드 표면. */
export function SurfaceCard({ as, className, children, ...rest }: SurfaceCardProps) {
  const Tag = as ?? "section";
  return (
    <Tag className={cx("surface-card", className)} {...rest}>
      {children}
    </Tag>
  );
}
