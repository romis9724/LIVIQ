// @vitest-environment jsdom
import { createRef } from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { SearchField } from "./SearchField";

describe("SearchField", () => {
  it("type=search 와 접근성 이름을 갖는다", () => {
    render(<SearchField label="민원 검색" />);
    const input = screen.getByRole("searchbox", { name: "민원 검색" });
    expect(input.getAttribute("type")).toBe("search");
  });

  it("uncontrolled ref로 값을 읽을 수 있다(한글 IME 대응)", () => {
    const ref = createRef<HTMLInputElement>();
    render(<SearchField label="검색" ref={ref} defaultValue="누수" />);
    expect(ref.current?.value).toBe("누수");
  });
});
