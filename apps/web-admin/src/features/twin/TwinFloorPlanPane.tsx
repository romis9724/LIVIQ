"use client";

import { useEffect, useState } from "react";
import { FloorPlanViewer, Skeleton } from "@liviq/ui";
import { ApiError, getFloorPlan, listFloorPlans, type AdminFloorPlanDetail } from "@/lib/api";
import { matchFloorPlanId } from "./twin-data";

type PlanState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; detail: AdminFloorPlanDetail | null };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

interface TwinFloorPlanPaneProps {
  /** null = 세대 타입 미상(매칭할 평면도가 없다). */
  unitTypeLabel: string | null;
}

/**
 * 세대 상세와 함께 열리는 평면도 패널 — 상세 스크림의 왼쪽(딤 영역) 전체를 차지한다.
 * 세대 타입으로 평면도를 찾아(목록 → 매칭 → 상세) 입주민과 동일한 뷰어로 보여준다.
 */
export function TwinFloorPlanPane({ unitTypeLabel }: TwinFloorPlanPaneProps) {
  const [state, setState] = useState<PlanState>({ kind: "loading" });

  useEffect(() => {
    if (!unitTypeLabel) {
      setState({ kind: "ready", detail: null });
      return;
    }
    let alive = true;
    setState({ kind: "loading" });
    (async (): Promise<PlanState> => {
      const plans = await listFloorPlans();
      const id = matchFloorPlanId(plans, unitTypeLabel);
      return { kind: "ready", detail: id ? await getFloorPlan(id) : null };
    })()
      .then((next) => {
        if (alive) setState(next);
      })
      .catch((err) => {
        if (alive) setState({ kind: "error", message: errorMessage(err) });
      });
    return () => {
      alive = false;
    };
  }, [unitTypeLabel]);

  return (
    <section className="twin-plan-pane" aria-label="세대 평면도">
      {/* 카드 안쪽 클릭은 상세를 닫지 않는다(바깥 여백 클릭은 그대로 닫힘). */}
      <div className="twin-plan-pane__card" onClick={(e) => e.stopPropagation()}>
        <h3 className="twin-plan-pane__title">
          {unitTypeLabel ? `${unitTypeLabel} 평면도` : "평면도"}
        </h3>
        {state.kind === "loading" ? (
          <Skeleton height="18rem" />
        ) : state.kind === "error" ? (
          <p className="twin-detail__empty">평면도를 불러오지 못했습니다. {state.message}</p>
        ) : !state.detail ? (
          <p className="twin-detail__empty">평면도 없음</p>
        ) : (
          <FloorPlanViewer plan={state.detail.plan} devices={state.detail.devices} />
        )}
      </div>
    </section>
  );
}
