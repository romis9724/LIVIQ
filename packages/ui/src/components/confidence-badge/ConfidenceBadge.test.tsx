// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ConfidenceBadge } from "./ConfidenceBadge";

// 절대규칙 1(출처/신뢰도) UI — status별 문구·글리프가 정확해야 한다.
describe("ConfidenceBadge", () => {
  it("handoff 상태는 담당자 연결 문구를 보인다", () => {
    render(<ConfidenceBadge status="handoff" />);
    expect(screen.getByText("담당자 연결")).toBeDefined();
  });

  it("answered 상태는 신뢰도 높음 문구를 보인다", () => {
    render(<ConfidenceBadge status="answered" />);
    expect(screen.getByText("답변됨 · 신뢰도 높음")).toBeDefined();
  });

  it("label prop으로 기본 문구를 재정의한다", () => {
    render(<ConfidenceBadge status="review" label="확인 대기" />);
    expect(screen.getByText("확인 대기")).toBeDefined();
  });
});
