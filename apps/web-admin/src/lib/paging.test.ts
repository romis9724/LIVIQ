// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { PAGE_SIZE, pageCount, usePaging } from "./paging";

const items = (n: number) => Array.from({ length: n }, (_, i) => i + 1);

describe("pageCount", () => {
  it("항목이 없어도 1페이지다", () => {
    expect(pageCount(0)).toBe(1);
  });

  it("남는 항목이 있으면 페이지를 하나 더 센다", () => {
    expect(pageCount(PAGE_SIZE)).toBe(1);
    expect(pageCount(PAGE_SIZE + 1)).toBe(2);
  });
});

describe("usePaging", () => {
  it("첫 페이지는 앞에서 PAGE_SIZE 건만 자른다", () => {
    const { result } = renderHook(() => usePaging(items(45)));

    expect(result.current.page).toBe(1);
    expect(result.current.totalPages).toBe(3);
    expect(result.current.rows).toEqual(items(PAGE_SIZE));
  });

  it("마지막 페이지는 남은 건수만 담는다", () => {
    const { result } = renderHook(() => usePaging(items(45)));

    act(() => result.current.setPage(3));

    expect(result.current.rows).toEqual([41, 42, 43, 44, 45]);
  });

  it("목록이 줄어 현재 페이지가 사라지면 마지막 페이지로 당긴다", () => {
    const { result, rerender } = renderHook(({ count }) => usePaging(items(count)), {
      initialProps: { count: 45 },
    });
    act(() => result.current.setPage(3));

    rerender({ count: 21 });

    expect(result.current.page).toBe(2);
    expect(result.current.rows).toEqual([21]);
  });

  it("pageSize를 넘기면 그 크기로 자른다 (문서관리 10건/페이지)", () => {
    const { result } = renderHook(() => usePaging(items(34), 10));

    expect(result.current.totalPages).toBe(4);
    expect(result.current.rows).toEqual(items(10));

    act(() => result.current.setPage(4));
    expect(result.current.rows).toEqual([31, 32, 33, 34]);
  });

  it("reset은 1페이지로 되돌린다", () => {
    const { result } = renderHook(() => usePaging(items(45)));
    act(() => result.current.setPage(3));

    act(() => result.current.reset());

    expect(result.current.page).toBe(1);
  });
});
