// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { AnswerBody } from "./AnswerBody";
import type { AssistantCitation } from "./assistant-events";

const CITATION: AssistantCitation = {
  ref: 1,
  documentId: "doc-1",
  documentTitle: "관리규약",
  quote: "위원의 임기는 2년으로 하며 연임할 수 있다.",
  page: 12,
  clause: "제32조",
  data: null,
};

describe("AnswerBody — 인라인 출처 배지(H20-4)", () => {
  it("citation 이 있는 [n] 은 배지로 렌더하고 툴팁에 제목·조항·인용문을 담는다", () => {
    // Arrange & Act
    render(<AnswerBody text="임기는 2년입니다 [1]" citations={[CITATION]} />);

    // Assert — 배지는 버튼(키보드 접근), 툴팁 내용은 DOM 에 존재.
    const badge = screen.getByRole("button", { name: "출처 1: 관리규약" });
    expect(badge.textContent).toBe("1");
    expect(screen.getByText("관리규약")).toBeDefined();
    expect(screen.getByText("제32조 · 12p")).toBeDefined();
    expect(screen.getByText(/임기는 2년으로 하며/)).toBeDefined();
  });

  it("클릭으로 열고 닫는다(aria-expanded)", () => {
    render(<AnswerBody text="임기는 2년입니다 [1]" citations={[CITATION]} />);
    const badge = screen.getByRole("button", { name: "출처 1: 관리규약" });
    expect(badge.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(badge);
    expect(badge.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(badge);
    expect(badge.getAttribute("aria-expanded")).toBe("false");
  });

  it("대응하는 citation 이 없는 번호는 배지 없이 벗긴다(기존 표시와 동일)", () => {
    render(<AnswerBody text="임기는 2년입니다 [7]" citations={[CITATION]} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("임기는 2년입니다")).toBeDefined();
  });

  it("citations 를 안 넘기면 기존과 같이 마커만 벗긴다", () => {
    render(<AnswerBody text="임기는 2년입니다 [1]" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("임기는 2년입니다")).toBeDefined();
  });
});
