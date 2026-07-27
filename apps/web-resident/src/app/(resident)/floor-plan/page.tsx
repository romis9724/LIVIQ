import type { Metadata } from "next";
import { FloorPlanView } from "@/features/floor-plan/FloorPlanView";

export const metadata: Metadata = {
  title: "우리집 평면도",
  description: "세대 평면도 · 전기·통신·급수·안전 시설 위치",
};

export default function FloorPlanPage() {
  return <FloorPlanView />;
}
