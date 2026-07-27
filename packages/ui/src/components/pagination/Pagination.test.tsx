// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { Pagination } from "./Pagination";

describe("Pagination", () => {
  it("nav 역할과 접근성 이름을 노출한다", () => {
    render(<Pagination page={1} totalPages={3} totalCount={45} onPage={() => {}} label="공지 목록 페이지" />);
    expect(screen.getByRole("navigation", { name: "공지 목록 페이지" })).toBeDefined();
  });

  it("현재 페이지·전체 페이지·전체 건수를 표시한다", () => {
    render(<Pagination page={2} totalPages={3} totalCount={1234} onPage={() => {}} />);
    expect(screen.getByText("2 / 3 페이지 · 1,234건")).toBeDefined();
  });

  it("첫 페이지에서는 이전만 비활성이다", () => {
    render(<Pagination page={1} totalPages={3} totalCount={45} onPage={() => {}} />);
    expect(screen.getByRole("button", { name: "이전" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "다음" }).hasAttribute("disabled")).toBe(false);
  });

  it("마지막 페이지에서는 다음만 비활성이다", () => {
    render(<Pagination page={3} totalPages={3} totalCount={45} onPage={() => {}} />);
    expect(screen.getByRole("button", { name: "이전" }).hasAttribute("disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "다음" }).hasAttribute("disabled")).toBe(true);
  });

  it("이전·다음 클릭 시 이웃 페이지 번호로 onPage를 호출한다", () => {
    const onPage = vi.fn();
    render(<Pagination page={2} totalPages={3} totalCount={45} onPage={onPage} />);

    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));

    expect(onPage).toHaveBeenNthCalledWith(1, 1);
    expect(onPage).toHaveBeenNthCalledWith(2, 3);
  });
});
