"use client";

import { useState } from "react";
import { FacilityAssistantPanel } from "./FacilityAssistantPanel";
import { FacilityGraphView } from "./FacilityGraphView";
import { FacilityManager } from "./FacilityManager";
import { FacilityOverlay } from "./FacilityOverlay";
import { FloorPlanManager } from "./FloorPlanManager";
import "./facilities.css";
import "./facilities-shell.css";

// 시설관리 메인 = 전체화면 3D 그래프 하나(H14-1 — 탭 3개 폐지). 목록·평면도·AI 도우미는
// 플로팅 버튼 → 오버레이로 연다. 목록은 그래프(3D canvas, 스크린리더 불가)의 **동등 기능
// 접근성 대체 수단**이라 진입 버튼을 본문 첫 요소(포커스 순서 맨 앞)에 둔다(ADR-0022 결정 6).

type Overlay =
  | { kind: "list" }
  | { kind: "plan"; planId: string | null }
  | { kind: "assistant" };

const OVERLAY_TITLE: Record<Overlay["kind"], string> = {
  list: "설비 목록",
  plan: "평면도 관리",
  assistant: "시설 AI 도우미",
};

export function FacilitiesScreen() {
  const [overlay, setOverlay] = useState<Overlay | null>(null);

  return (
    <div className="fac-screen">
      <h1 id="main" className="sr-only">
        시설 관리
      </h1>

      <div className="fac-dock" role="group" aria-label="시설 관리 도구">
        <button
          type="button"
          className="fac-dock__btn"
          onClick={() => setOverlay({ kind: "list" })}
        >
          <span className="fac-dock__icon" aria-hidden="true">📋</span> 설비 목록·등록
        </button>
        <button
          type="button"
          className="fac-dock__btn"
          onClick={() => setOverlay({ kind: "plan", planId: null })}
        >
          <span className="fac-dock__icon" aria-hidden="true">🗺</span> 평면도 관리
        </button>
        <button
          type="button"
          className="fac-dock__btn"
          onClick={() => setOverlay({ kind: "assistant" })}
        >
          <span className="fac-dock__icon" aria-hidden="true">🤖</span> AI 도우미
        </button>
      </div>

      <FacilityGraphView
        onOpenList={() => setOverlay({ kind: "list" })}
        onEditFloorPlan={(planId) => setOverlay({ kind: "plan", planId })}
      />

      {overlay ? (
        <FacilityOverlay title={OVERLAY_TITLE[overlay.kind]} onClose={() => setOverlay(null)}>
          {overlay.kind === "list" ? <FacilityManager /> : null}
          {overlay.kind === "plan" ? <FloorPlanManager initialPlanId={overlay.planId} /> : null}
          {overlay.kind === "assistant" ? <FacilityAssistantPanel /> : null}
        </FacilityOverlay>
      ) : null}
    </div>
  );
}
