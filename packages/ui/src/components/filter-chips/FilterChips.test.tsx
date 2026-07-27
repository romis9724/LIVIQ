// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { FilterChips } from "./FilterChips";

const ITEMS = [
  { id: "all", label: "전체", count: 12 },
  { id: "open", label: "미처리" },
] as const;

describe("FilterChips", () => {
  it("tablist 역할과 접근성 이름을 노출한다", () => {
    render(<FilterChips items={ITEMS} value="all" onChange={() => {}} label="상태 필터" />);
    expect(screen.getByRole("tablist", { name: "상태 필터" })).toBeDefined();
  });

  it("선택된 칩만 aria-selected=true 다", () => {
    render(<FilterChips items={ITEMS} value="open" onChange={() => {}} label="상태 필터" />);
    expect(screen.getByRole("tab", { name: /미처리/ }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: /전체/ }).getAttribute("aria-selected")).toBe("false");
  });

  it("count가 있는 항목만 뱃지를 렌더한다", () => {
    const { container } = render(
      <FilterChips items={ITEMS} value="all" onChange={() => {}} label="상태 필터" />,
    );
    expect(container.querySelectorAll(".filter-chip__count").length).toBe(1);
    expect(screen.getByText("12")).toBeDefined();
  });

  it("클릭 시 해당 id로 onChange를 호출한다", () => {
    const onChange = vi.fn();
    render(<FilterChips items={ITEMS} value="all" onChange={onChange} label="상태 필터" />);
    fireEvent.click(screen.getByRole("tab", { name: "미처리" }));
    expect(onChange).toHaveBeenCalledWith("open");
  });
});
