// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("status에 대응하는 기본 라벨을 렌더한다", () => {
    render(<StatusPill status="done" />);
    expect(screen.getByText("완료")).toBeDefined();
  });

  it("label prop이 기본 라벨을 재정의한다", () => {
    render(<StatusPill status="received" label="대기" />);
    expect(screen.getByText("대기")).toBeDefined();
  });

  it("status modifier 클래스를 적용한다", () => {
    const { container } = render(<StatusPill status="fault" />);
    const pill = container.querySelector(".status-pill");
    expect(pill?.className).toContain("status-pill--fault");
  });
});
