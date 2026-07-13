// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

import { Approvals } from "./Approvals";

// globals 미사용 → 렌더 누적 방지를 위해 명시적 cleanup.
afterEach(cleanup);

describe("Approvals", () => {
  it("PII를 마스킹해 노출한다 (성함·생년월일)", () => {
    render(<Approvals />);
    expect(screen.getByText("홍*동")).toBeDefined();
    expect(screen.getAllByText("19**-**-**").length).toBeGreaterThan(0);
  });

  it("명부 일치/불일치 배지를 노출한다", () => {
    const { container } = render(<Approvals />);
    expect(container.querySelectorAll(".apv-match--ok").length).toBe(3);
    expect(container.querySelectorAll(".apv-match--warn").length).toBe(2);
  });

  it("승인하면 대기 건수가 줄고 '승인됨' 상태가 표시된다", () => {
    const { container } = render(<Approvals />);
    const count = () => container.querySelector(".apv-count")?.textContent;

    expect(count()).toBe("5건 대기");
    fireEvent.click(screen.getAllByRole("button", { name: "승인" })[0]!);
    expect(count()).toBe("4건 대기");
    expect(screen.getByText("승인됨")).toBeDefined();
  });

  it("거절은 사유 입력 전까지 확정 버튼이 비활성", () => {
    render(<Approvals />);
    fireEvent.click(screen.getAllByRole("button", { name: "거절" })[0]!);

    const confirm = screen.getByRole("button", { name: "거절 확정" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/거절 사유/), {
      target: { value: "명부 미등록 세대" },
    });
    expect(confirm.disabled).toBe(false);
  });

  it("모든 신청을 처리하면 빈 상태를 보여준다", () => {
    render(<Approvals />);
    // 5건을 모두 승인.
    for (let i = 0; i < 5; i += 1) {
      fireEvent.click(screen.getAllByRole("button", { name: "승인" })[0]!);
    }
    expect(screen.getByText("대기 중인 가입 신청이 없습니다")).toBeDefined();
  });
});
