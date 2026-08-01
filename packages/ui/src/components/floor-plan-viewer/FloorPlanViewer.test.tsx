// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { FloorPlanViewer, type FloorPlanViewerDevice } from "./FloorPlanViewer";

const plan = { imageUrl: "/plan.png", imageWidth: 1000, imageHeight: 800, unitTypeName: "84A" };

const device = (over: Partial<FloorPlanViewerDevice>): FloorPlanViewerDevice => ({
  id: "d1",
  deviceType: "콘센트",
  x: 100,
  y: 100,
  room: "거실",
  dir: null,
  label: null,
  memo: null,
  ...over,
});

const devices: readonly FloorPlanViewerDevice[] = [
  device({ id: "d1", room: "거실" }),
  device({ id: "d2", room: "주방" }),
  device({ id: "d3", deviceType: "보일러", room: "다용도실" }),
];

describe("FloorPlanViewer highlightLabels", () => {
  it("라벨과 일치하는 마커를 모두 강조하고 첫 마커를 선택 상태로 연다", () => {
    // Arrange·Act — AI 비서 딥링크(?device=거실 콘센트)로 들어온 경우
    const { container } = render(
      <FloorPlanViewer plan={plan} devices={devices} highlightLabels={["거실 콘센트"]} />,
    );

    // Assert — 거실 콘센트만 강조(주방 콘센트·보일러 제외 — 시각 실측으로 과잉 강조 정정),
    // 첫 마커 팝오버 열림
    expect(container.querySelectorAll("[data-highlight]")).toHaveLength(1);
    expect(screen.getAllByLabelText("거실 콘센트 — 찾는 위치")).toHaveLength(1);
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("방 없는 라벨은 전 방의 같은 종류를 강조한다", () => {
    const { container } = render(
      <FloorPlanViewer plan={plan} devices={devices} highlightLabels={["콘센트"]} />,
    );

    // 거실·주방 콘센트 2곳 — "안방 콘센트" ⊃ "콘센트" 방향의 부분 일치가 이를 담당한다.
    expect(container.querySelectorAll("[data-highlight]")).toHaveLength(2);
  });

  it("강조 라벨이 없으면 기존과 같이 강조·선택 없이 렌더한다", () => {
    const { container } = render(<FloorPlanViewer plan={plan} devices={devices} />);

    expect(container.querySelectorAll("[data-highlight]")).toHaveLength(0);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("일치하는 기기가 없으면 강조 없이 평면도만 보여준다(오류 아님)", () => {
    const { container } = render(
      <FloorPlanViewer plan={plan} devices={devices} highlightLabels={["화재감지기"]} />,
    );

    expect(container.querySelectorAll("[data-highlight]")).toHaveLength(0);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByAltText("84A 평면도")).toBeDefined();
  });
});
