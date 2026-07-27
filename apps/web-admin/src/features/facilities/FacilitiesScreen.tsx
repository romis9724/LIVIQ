"use client";

import { useState } from "react";
import { FacilityGraphView } from "./FacilityGraphView";
import { FacilityManager } from "./FacilityManager";
import { FloorPlanManager } from "./FloorPlanManager";
import "./facilities.css";

// 시설관리 메인 = 3D 그래프(ADR-0022). 목록 뷰는 폐기가 아니라 **동등 기능의 접근성 대체 수단**이라
// 같은 화면의 토글로 항상 도달 가능해야 한다(3D canvas 는 스크린리더로 읽히지 않는다 — 결정 6).
// 그래서 토글을 포커스 순서 맨 앞(본문 첫 요소)에 둔다. 평면도(H13-4)는 별개 편집 화면이라 세 번째 탭.

type FacilityView = "graph" | "list" | "plan";
const VIEWS: readonly { id: FacilityView; label: string }[] = [
  { id: "graph", label: "그래프" },
  { id: "list", label: "목록" },
  { id: "plan", label: "평면도" },
];

export function FacilitiesScreen() {
  const [view, setView] = useState<FacilityView>("graph");

  return (
    <>
      <div className="fac-viewtabs" role="tablist" aria-label="시설 보기 방식">
        {VIEWS.map((option) => (
          <button
            key={option.id}
            type="button"
            role="tab"
            aria-selected={view === option.id}
            className="fac-viewtab"
            data-active={view === option.id || undefined}
            onClick={() => setView(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {view === "graph" ? (
        <FacilityGraphView onSwitchToList={() => setView("list")} />
      ) : view === "list" ? (
        <FacilityManager />
      ) : (
        <FloorPlanManager />
      )}
    </>
  );
}
