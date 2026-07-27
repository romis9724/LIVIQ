import type { Metadata } from "next";
import { FacilitiesScreen } from "@/features/facilities/FacilitiesScreen";

export const metadata: Metadata = {
  title: "시설 관리",
  description: "시설 3D 그래프 · 운영 상태 · AI 가능 원인 후보",
};

export default function FacilitiesPage() {
  return <FacilitiesScreen />;
}
