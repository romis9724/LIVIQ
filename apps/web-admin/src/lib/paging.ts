"use client";

import { useState } from "react";

/** 목록 화면 공용 클라이언트 페이징 — 전량 로드하는 화면에서 한 페이지 분량만 렌더한다. */
export const PAGE_SIZE = 20;

/** 항상 1 이상 — 항목이 없어도 "1 / 1 페이지"로 표기가 깨지지 않게. */
export function pageCount(total: number): number {
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}

export interface Paging<T> {
  /** 범위 밖 값이 들어와도 1..totalPages 로 보정된 현재 페이지. */
  page: number;
  totalPages: number;
  /** 현재 페이지에 해당하는 항목들. */
  rows: readonly T[];
  setPage: (page: number) => void;
  /** 필터·검색이 바뀔 때 호출 — 1페이지로 되돌린다. */
  reset: () => void;
}

/**
 * 필터링까지 끝난 목록 전체를 받아 현재 페이지 조각을 돌려준다.
 * 목록이 줄어 현재 페이지가 사라지면 마지막 페이지로 당긴다(빈 화면 방지).
 */
export function usePaging<T>(items: readonly T[]): Paging<T> {
  const [page, setPage] = useState(1);
  const totalPages = pageCount(items.length);
  const current = Math.min(Math.max(page, 1), totalPages);
  const start = (current - 1) * PAGE_SIZE;
  return {
    page: current,
    totalPages,
    rows: items.slice(start, start + PAGE_SIZE),
    setPage,
    reset: () => setPage(1),
  };
}
