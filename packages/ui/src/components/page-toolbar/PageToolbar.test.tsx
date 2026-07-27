// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { PageToolbar } from "./PageToolbar";

describe("PageToolbar", () => {
  it("좌·우 슬롯을 각각 렌더한다", () => {
    render(<PageToolbar start={<span>필터</span>} end={<span>검색</span>} />);
    expect(screen.getByText("필터")).toBeDefined();
    expect(screen.getByText("검색")).toBeDefined();
  });

  it("주어지지 않은 슬롯은 빈 div를 남기지 않는다", () => {
    const { container } = render(<PageToolbar end={<span>검색</span>} />);
    expect(container.querySelector(".page-toolbar__start")).toBeNull();
    expect(container.querySelector(".page-toolbar__end")).not.toBeNull();
  });
});
