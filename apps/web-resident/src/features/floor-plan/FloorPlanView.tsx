"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { EmptyState, FloorPlanViewer, Skeleton } from "@liviq/ui";
import { getMyFloorPlan, type FloorPlanData } from "./api";
import { readDeviceParam } from "./links";
import "./floor-plan.css";

type LoadState = "loading" | "empty" | "error" | "ready";

export function FloorPlanView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [state, setState] = useState<LoadState>("loading");
  const [data, setData] = useState<FloorPlanData | null>(null);

  useEffect(() => {
    let alive = true;
    getMyFloorPlan()
      .then((result) => {
        if (!alive) return;
        setData(result);
        setState(result ? "ready" : "empty");
      })
      .catch(() => alive && setState("error"));
    return () => {
      alive = false;
    };
  }, []);

  // AI 비서가 찾은 위치(`?device=`) — 없으면 평소의 평면도 그대로다.
  const highlightLabels = useMemo(() => readDeviceParam(searchParams), [searchParams]);

  return (
    <div className="floor-plan">
      <header className="floor-plan__header">
        <button
          type="button"
          className="floor-plan__back"
          aria-label="뒤로가기"
          onClick={() => router.back()}
        >
          ←
        </button>
        <h1 id="main" className="floor-plan__title">
          우리집 평면도
        </h1>
      </header>

      <main className="floor-plan__main">
        {state === "loading" ? (
          <Skeleton height="18rem" />
        ) : state === "error" ? (
          <EmptyState
            icon="⚠"
            title="평면도를 불러오지 못했습니다"
            description="잠시 후 다시 시도해 주세요."
          />
        ) : state === "empty" || !data ? (
          <EmptyState
            icon="🏠"
            title="평면도가 아직 준비되지 않았습니다"
            description="세대 평면도 등록 문의는 관리사무소로 연락해 주세요."
          />
        ) : (
          <>
            {data.plan.unitTypeName ? (
              <p className="floor-plan__unit-type">{data.plan.unitTypeName} 타입</p>
            ) : null}
            {highlightLabels.length > 0 ? (
              <p className="floor-plan__highlight">
                <span aria-hidden="true">📍</span> AI 비서가 찾은 위치 {highlightLabels.join(" · ")}{" "}
                — 평면도에 강조 표시했어요.
              </p>
            ) : null}
            <FloorPlanViewer
              plan={data.plan}
              devices={data.devices}
              highlightLabels={highlightLabels}
            />
          </>
        )}
      </main>
    </div>
  );
}
