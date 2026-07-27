import { Button } from "../button/Button";
import { cx } from "../../lib/cx";

export interface PaginationProps {
  /** 현재 페이지(1-base). */
  page: number;
  totalPages: number;
  /** 페이지가 아니라 목록 전체 건수. */
  totalCount: number;
  onPage: (page: number) => void;
  /** nav 접근성 이름 (예: "공지 목록 페이지"). */
  label?: string;
  className?: string;
}

/** 목록 표 하단 페이저 — 이전/다음 + "n / N 페이지 · x건"(docs/05 §5A, 기준: 주민 명부). */
export function Pagination({
  page,
  totalPages,
  totalCount,
  onPage,
  label = "페이지 이동",
  className,
}: PaginationProps) {
  return (
    <nav className={cx("pagination", className)} aria-label={label}>
      <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        이전
      </Button>
      <span className="pagination__status" aria-live="polite">
        {page} / {totalPages} 페이지 · {totalCount.toLocaleString()}건
      </span>
      <Button
        variant="ghost"
        size="sm"
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
      >
        다음
      </Button>
    </nav>
  );
}
