// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { StatCard, StatGrid } from "./StatCard";

describe("StatCard", () => {
  it("라벨과 값·단위를 렌더한다", () => {
    render(<StatCard label="미처리 민원" value={12} unit="건" />);
    expect(screen.getByText("미처리 민원")).toBeDefined();
    expect(screen.getByText("12")).toBeDefined();
    expect(screen.getByText("건")).toBeDefined();
  });

  it("tone은 값 색만 바꾼다(카드 배경 클래스 불변)", () => {
    const { container } = render(<StatCard label="장애" value={3} tone="danger" />);
    const card = container.querySelector(".stat-card");
    const value = container.querySelector(".stat-card__value");
    expect(card?.className).toBe("stat-card");
    expect(value?.className).toContain("stat-card__value--danger");
  });

  it("tone 기본값은 modifier 클래스를 붙이지 않는다", () => {
    const { container } = render(<StatCard label="전체" value={7} />);
    expect(container.querySelector(".stat-card__value")?.className).toBe("stat-card__value");
  });

  it("StatGrid는 자식을 grid 컨테이너로 감싼다", () => {
    const { container } = render(
      <StatGrid>
        <StatCard label="전체" value={1} />
      </StatGrid>,
    );
    expect(container.querySelector(".stat-grid > .stat-card")).not.toBeNull();
  });
});
