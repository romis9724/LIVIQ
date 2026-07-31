// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { FeedbackButtons } from "./FeedbackButtons";

// 아이콘만 남긴 버튼이라 접근 가능한 이름(aria-label)이 사라지면 스크린리더에서 익명 버튼이 된다.
describe("FeedbackButtons", () => {
  it("아이콘만 노출해도 접근 가능한 이름을 유지한다", () => {
    render(<FeedbackButtons />);
    expect(screen.getByRole("button", { name: "도움돼요" })).toBeDefined();
    expect(screen.getByRole("button", { name: "아쉬워요" })).toBeDefined();
  });

  it("defaultValue 를 aria-pressed 로 반영한다", () => {
    render(<FeedbackButtons defaultValue="up" />);
    expect(screen.getByRole("button", { name: "도움돼요" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(screen.getByRole("button", { name: "아쉬워요" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
  });
});
