// @vitest-environment jsdom
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";

import type { ParkingLayout, ParkingOccupancy } from "@/lib/api";

// api 모듈을 목킹 — 뷰가 점유 정본(getParkingOccupancy)을 bySpot 으로 옮겨
// 현황·톤을 그리는 배선만 검증한다(시뮬레이션 은퇴 후).
const getParkingLayout = vi.fn();
const getParkingOccupancy = vi.fn();

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  getParkingLayout: () => getParkingLayout(),
  getParkingOccupancy: () => getParkingOccupancy(),
}));

import { ParkingView } from "./ParkingView";

const LAYOUT: ParkingLayout = {
  viewBox: "0 0 1200 400",
  buildings: [{ name: "401동", outline: [[0, 0]], cx: 5, cy: 5 }],
  boxes: [],
  cores: [{ name: "401동", x: 100, y: 100, w: 72, h: 128 }],
  spots: [
    { no: "001", kind: "일반", x: 100, y: 162, dir: "up" },
    { no: "002", kind: "일반", x: 140, y: 162, dir: "down" },
    { no: "003", kind: "일반", x: 180, y: 162, dir: "up" },
  ],
};

const OCCUPANCY: ParkingOccupancy[] = [
  {
    spotNo: "001",
    isExternal: false,
    dong: "401동",
    ho: "301호",
    model: "아이오닉5",
    plate: "12가3456",
    parkedHours: 2,
  },
  {
    spotNo: "002",
    isExternal: true,
    dong: null,
    ho: null,
    model: null,
    plate: "99바7788",
    parkedHours: 30,
  },
];

beforeEach(() => {
  getParkingLayout.mockResolvedValue(LAYOUT);
  getParkingOccupancy.mockResolvedValue([...OCCUPANCY]);
});

afterEach(() => {
  vi.clearAllMocks();
  cleanup();
});

function tileValue(label: string): string {
  const summary = screen.getByLabelText("주차 현황 요약");
  const li = within(summary).getByText(label).closest("li");
  return li?.querySelector(".pk-tile__value")?.textContent ?? "";
}

describe("ParkingView", () => {
  it("builds occupancy summary counts from the server occupancy (not a client sim)", async () => {
    render(<ParkingView />);

    await waitFor(() => expect(getParkingOccupancy).toHaveBeenCalledTimes(1));
    await screen.findByLabelText("주차 현황 요약");

    // 3면 중 001 입주민·002 외부 점유, 003 빈자리.
    expect(tileValue("전체 면")).toContain("3");
    expect(tileValue("주차")).toContain("2");
    expect(tileValue("입주민")).toContain("1");
    expect(tileValue("외부")).toContain("1");
    expect(tileValue("빈자리")).toContain("1");
  });

  it("renders resident and external tones per spot from bySpot", async () => {
    const { container } = render(<ParkingView />);

    await screen.findByLabelText("주차 현황 요약");

    expect(container.querySelector('[data-no="001"]')?.getAttribute("data-state")).toBe("resident");
    expect(container.querySelector('[data-no="002"]')?.getAttribute("data-state")).toBe("external");
    expect(container.querySelector('[data-no="003"]')?.getAttribute("data-state")).toBe("empty");
  });

  it("shows the external-car group chip with its count", async () => {
    render(<ParkingView />);

    expect(await screen.findByText("외부 1대")).toBeTruthy();
  });
});
