import { describe, expect, it } from "vitest";
import type { ParkingMapSpot } from "@liviq/ui";
import type { ParkingCore } from "./api";
import { buildSpotDetail, coreDistanceM } from "./spot-detail";

// 코어 중심 (100, 100), 면 중심 (100+13*4=152? ) — 거리 계산은 실값으로 검증한다.
const CORE: ParkingCore = { name: "401동", x: 64, y: 36, w: 72, h: 128 };
// 면 중심 = (x+17, y+32). CORE 중심 = (100, 100).
const SPOT: ParkingMapSpot = { no: "217", kind: "일반", x: 213, y: 68, dir: "up" };
// dx = 230-100 = 130px, dy = 100-100 = 0 → 130px * (1/13) = 10m

describe("coreDistanceM", () => {
  it("면 중심↔코어 중심 유클리드(px)를 13px/m 축척으로 환산한다", () => {
    expect(coreDistanceM(SPOT, CORE)).toBe(10);
  });

  it("코어가 없으면 null — 거리 줄을 그리지 않는다", () => {
    expect(coreDistanceM(SPOT, undefined)).toBeNull();
  });
});

describe("buildSpotDetail", () => {
  const base = {
    spot: SPOT,
    isOccupied: false,
    mine: undefined,
    recommendIndex: -1,
    myDong: "401동",
    core: CORE,
    nowMs: Date.parse("2026-08-03T12:00:00Z"),
  };

  it("빈 일반 면 — 상태·거리", () => {
    const detail = buildSpotDetail(base);
    expect(detail.title).toBe("217면 · 일반");
    expect(detail.lines).toEqual(["지금 비어 있어요.", "401동 승강기까지 약 10m"]);
  });

  it("추천 자리는 순위를 함께 쓴다", () => {
    const detail = buildSpotDetail({ ...base, recommendIndex: 0 });
    expect(detail.lines).toContain("AI 비서 추천 자리 1순위예요.");
  });

  it("내 차 면 — 입차 경과를 함께 쓴다", () => {
    const detail = buildSpotDetail({
      ...base,
      mine: { spotNo: "217", entryAt: "2026-08-03T10:00:00Z" },
    });
    expect(detail.lines[0]).toMatch(/^내 차가 주차되어 있어요 · .*전 입차$/);
  });

  it("타 차량 점유 면 — 점유 사실만(소속·차종 없음, 규칙 2)", () => {
    const detail = buildSpotDetail({ ...base, isOccupied: true });
    expect(detail.lines[0]).toBe("다른 차량이 주차 중이에요.");
  });

  it("전기차 면 라벨", () => {
    const detail = buildSpotDetail({ ...base, spot: { ...SPOT, kind: "전기차" } });
    expect(detail.title).toBe("217면 · 전기차 충전 ⚡");
  });
});
