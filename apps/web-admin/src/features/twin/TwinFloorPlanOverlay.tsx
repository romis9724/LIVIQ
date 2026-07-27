"use client";

import { useEffect, useState } from "react";
import { Skeleton } from "@liviq/ui";
import {
  ApiError,
  getFloorPlan,
  listFloorPlans,
  type AdminFloorPlanDetail,
} from "@/lib/api";
import { markerLabel, toPercent } from "@/features/facilities/floor-plan-admin-data";
import { matchFloorPlanId } from "./twin-data";

type PlanState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; detail: AdminFloorPlanDetail | null };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

interface TwinFloorPlanOverlayProps {
  unitTypeLabel: string;
  onClose: () => void;
}

/**
 * 세대 평면도 오버레이(H14-3) — 왼쪽 3D 무대 전체를 덮는 반투명 레이어(뒤 건물이 비친다).
 * 열릴 때만 평면도를 불러온다(목록 → 타입 매칭 → 상세). 상세 패널은 오른쪽에 그대로 남는다.
 */
export function TwinFloorPlanOverlay({ unitTypeLabel, onClose }: TwinFloorPlanOverlayProps) {
  const [state, setState] = useState<PlanState>({ kind: "loading" });

  useEffect(() => {
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

  // 열려 있는 동안 Escape 로 닫기(상세 패널은 이때 Escape 를 무시한다 — 평면도만 닫힌다).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const title = `${unitTypeLabel} 평면도`;
  return (
    <div className="twin-plan-overlay" role="dialog" aria-label={title}>
      <div className="twin-plan-overlay__bar">
        <h3 className="twin-plan-overlay__title">{title}</h3>
        <button
          type="button"
          className="twin-detail__close"
          aria-label="평면도 닫기"
          autoFocus
          onClick={onClose}
        >
          ✕
        </button>
      </div>
      <div className="twin-plan-overlay__stage">
        {state.kind === "loading" ? (
          <Skeleton height="14rem" />
        ) : state.kind === "error" ? (
          <p className="twin-detail__empty">평면도를 불러오지 못했습니다. {state.message}</p>
        ) : !state.detail ? (
          <p className="twin-detail__empty">평면도 없음</p>
        ) : (
          <ReadOnlyFloorPlan detail={state.detail} />
        )}
      </div>
    </div>
  );
}

function ReadOnlyFloorPlan({ detail }: { detail: AdminFloorPlanDetail }) {
  const { plan, devices } = detail;
  return (
    <div className="twin-plan__canvas">
      {/* eslint-disable-next-line @next/next/no-img-element -- 서명 URL(외부 오리진) — 읽기 전용 뷰 */}
      <img
        src={plan.imageUrl}
        alt={`${plan.unitTypeName} 평면도`}
        className="twin-plan__image"
        width={plan.imageWidth}
        height={plan.imageHeight}
      />
      {devices.map((d) => {
        const label = markerLabel({ room: d.room, deviceType: d.deviceType, label: d.label });
        return (
          <button
            key={d.id}
            type="button"
            className="twin-plan__marker"
            title={label}
            aria-label={label}
            style={{
              left: `${toPercent(d.x, plan.imageWidth)}%`,
              top: `${toPercent(d.y, plan.imageHeight)}%`,
            }}
          />
        ); // ponytail: 마커는 읽기 전용(클릭 동작 없음) — 편집은 시설관리 평면도 화면에서.
      })}
    </div>
  );
}
