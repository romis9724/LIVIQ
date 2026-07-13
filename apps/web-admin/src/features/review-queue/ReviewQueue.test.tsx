// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

import { ReviewQueue } from "./ReviewQueue";

// globals 미사용 → 렌더 누적 방지를 위해 명시적 cleanup.
afterEach(cleanup);

// 절대규칙 1(출처 없으면 지어내지 않음)·6(위험 출력 사람 검수) 의 UI 강제.
describe("ReviewQueue", () => {
  it("출처 없는 저신뢰 답변은 승인 불가 + 담당자 연결 권고를 노출한다", () => {
    render(<ReviewQueue />);
    expect(
      screen.getByRole("button", { name: "승인 불가 (출처 없음)" }),
    ).toBeDefined();
    expect(screen.getByText("근거 문서를 찾지 못함")).toBeDefined();
    expect(screen.getAllByText(/담당자 연결/).length).toBeGreaterThan(0);
  });

  it("출처 있는 답변은 승인 버튼이 활성", () => {
    render(<ReviewQueue />);
    // '수정 후 승인'과 구분: 정확 일치(anchor)
    const approve = screen.getByRole("button", {
      name: /^승인$/,
    }) as HTMLButtonElement;
    expect(approve.disabled).toBe(false);
  });

  it("반려하면 큐에서 제거되어 대기 건수가 준다", () => {
    const { container } = render(<ReviewQueue />);
    const count = () =>
      container.querySelector(".rq-head__count")?.textContent;

    expect(count()).toBe("2건 대기");
    fireEvent.click(screen.getAllByRole("button", { name: "반려" })[0]!);
    expect(count()).toBe("1건 대기");
  });
});
