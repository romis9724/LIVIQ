// 주차면 상세 문구(H20-5) — 면 클릭 시 하단 패널에 보여줄 내용을 순수 함수로 만든다.
// 거리·경과 등 수치는 전부 여기서 확정한다(표시 계층은 조립만).

import { SPOT_H, SPOT_W, elapsedText, type ParkingMapSpot } from "@liviq/ui";
import type { MyParkedVehicle, ParkingCore } from "./api";

/** 배치도 축척 — 면 34x64px = 2.5m x 5.0m (ai-core geometry.PX_TO_M와 동일해야 한다). */
const PX_TO_M = 1 / 13;

const KIND_LABEL: Record<string, string> = {
  일반: "일반",
  장애인: "장애인 전용 ♿",
  전기차: "전기차 충전 ⚡",
};

export interface SpotDetail {
  /** "217면 · 일반" */
  title: string;
  /** 상태·거리·추천 순위 등 — 위에서 아래 순서로 그린다. */
  lines: string[];
}

/** 면 중심 ↔ 코어 중심 거리(m, 반올림). 코어가 없으면 null. */
export function coreDistanceM(spot: ParkingMapSpot, core: ParkingCore | undefined): number | null {
  if (!core) return null;
  const dx = spot.x + SPOT_W / 2 - (core.x + core.w / 2);
  const dy = spot.y + SPOT_H / 2 - (core.y + core.h / 2);
  return Math.round(Math.hypot(dx, dy) * PX_TO_M);
}

export function buildSpotDetail(input: {
  spot: ParkingMapSpot;
  isOccupied: boolean;
  mine: MyParkedVehicle | undefined;
  /** AI 추천 목록에서의 0-기반 순서 — 없으면 -1. */
  recommendIndex: number;
  myDong: string | null;
  core: ParkingCore | undefined;
  nowMs: number;
}): SpotDetail {
  const { spot, isOccupied, mine, recommendIndex, myDong, core, nowMs } = input;
  const lines: string[] = [];

  if (mine) {
    const entryMs = mine.entryAt ? Date.parse(mine.entryAt) : Number.NaN;
    lines.push(
      Number.isNaN(entryMs)
        ? "내 차가 주차되어 있어요."
        : `내 차가 주차되어 있어요 · ${elapsedText(entryMs, nowMs)} 전 입차`,
    );
  } else {
    lines.push(isOccupied ? "다른 차량이 주차 중이에요." : "지금 비어 있어요.");
  }

  if (recommendIndex >= 0) lines.push(`AI 비서 추천 자리 ${recommendIndex + 1}순위예요.`);

  const distance = coreDistanceM(spot, core);
  if (distance !== null && myDong) {
    lines.push(`${myDong} 승강기까지 약 ${distance}m`);
  }

  return {
    title: `${spot.no}면 · ${KIND_LABEL[spot.kind] ?? spot.kind}`,
    lines,
  };
}
