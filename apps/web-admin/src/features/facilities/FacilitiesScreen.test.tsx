// @vitest-environment jsdom
// 전체화면 그래프 + 오버레이 오케스트레이션(H14-1) — 탭이 아니라 플로팅 버튼으로 여닫는다.
// 3D 캔버스(three)는 mock — 여기서 검증할 것은 오버레이 열림/닫힘과 평면도 진입 경로다.
import { describe, it, expect, afterEach, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const graphViewProps = vi.fn();

vi.mock("./FacilityGraphView", () => ({
  FacilityGraphView: (props: { onEditFloorPlan: (planId: string) => void }) => {
    graphViewProps(props);
    return (
      <button type="button" onClick={() => props.onEditFloorPlan("fp-1")}>
        도면 노드 클릭
      </button>
    );
  },
}));
vi.mock("./FacilityManager", () => ({ FacilityManager: () => <p>설비 목록 본문</p> }));
vi.mock("./FloorPlanManager", () => ({
  FloorPlanManager: ({ initialPlanId }: { initialPlanId?: string | null }) => (
    <p>평면도 본문 {initialPlanId ?? "목록"}</p>
  ),
}));
vi.mock("./FacilityAssistantPanel", () => ({
  FacilityAssistantPanel: () => <p>AI 도우미 본문</p>,
}));

import { FacilitiesScreen } from "./FacilitiesScreen";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FacilitiesScreen 오버레이", () => {
  it("기본은 그래프만 — 오버레이는 열려 있지 않다", () => {
    render(<FacilitiesScreen />);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText("설비 목록 본문")).toBeNull();
  });

  it("‘설비 목록·등록’ 버튼이 목록 오버레이를 연다(3D 대체 수단 — ADR-0022 결정 6)", () => {
    render(<FacilitiesScreen />);

    fireEvent.click(screen.getByRole("button", { name: /설비 목록·등록/ }));

    expect(screen.getByRole("dialog", { name: "설비 목록" })).toBeDefined();
    expect(screen.getByText("설비 목록 본문")).toBeDefined();
  });

  it("닫기 버튼과 Esc 로 오버레이를 닫는다", () => {
    render(<FacilitiesScreen />);

    fireEvent.click(screen.getByRole("button", { name: /AI 도우미/ }));
    expect(screen.getByText("AI 도우미 본문")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /AI 도우미/ }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("그래프의 평면도 노드에서 편집을 요청하면 해당 도면으로 오버레이가 열린다", () => {
    render(<FacilitiesScreen />);

    fireEvent.click(screen.getByRole("button", { name: "도면 노드 클릭" }));

    expect(screen.getByRole("dialog", { name: "평면도 관리" })).toBeDefined();
    expect(screen.getByText("평면도 본문 fp-1")).toBeDefined();
  });

  it("플로팅 ‘평면도 관리’ 버튼은 도면 목록부터 연다", () => {
    render(<FacilitiesScreen />);

    fireEvent.click(screen.getByRole("button", { name: /평면도 관리/ }));

    expect(screen.getByText("평면도 본문 목록")).toBeDefined();
  });
});
