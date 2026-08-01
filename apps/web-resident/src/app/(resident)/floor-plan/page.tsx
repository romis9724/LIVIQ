import type { Metadata } from "next";
import { Suspense } from "react";
import { FloorPlanView } from "@/features/floor-plan/FloorPlanView";

export const metadata: Metadata = {
  title: "우리집 평면도",
  description: "세대 평면도 · 전기·통신·급수·안전 시설 위치",
};

export default function FloorPlanPage() {
  // FloorPlanView 가 useSearchParams(?device= AI 비서 딥링크)를 쓴다 — App Router 는 Suspense 경계 필수.
  return (
    <Suspense>
      <FloorPlanView />
    </Suspense>
  );
}
