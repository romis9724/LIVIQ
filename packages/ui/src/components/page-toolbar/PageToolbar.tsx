import type { ReactNode } from "react";
import { cx } from "../../lib/cx";

export interface PageToolbarProps {
  /** 좌측 슬롯 — 필터 칩(FilterChips) 영역. */
  start?: ReactNode;
  /** 우측 슬롯 — 검색(SearchField) + 주요 액션 1개. */
  end?: ReactNode;
  className?: string;
}

/** 목록 화면 툴바 — 페이지당 1개, 44px 라인, 좁은 화면에서 wrap(docs/05 §5A). */
export function PageToolbar({ start, end, className }: PageToolbarProps) {
  return (
    <div className={cx("page-toolbar", className)}>
      {start ? <div className="page-toolbar__start">{start}</div> : null}
      {end ? <div className="page-toolbar__end">{end}</div> : null}
    </div>
  );
}
