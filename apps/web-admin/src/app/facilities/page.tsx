import type { Metadata } from "next";
import { FacilityManager } from "@/features/facilities/FacilityManager";

export const metadata: Metadata = {
  title: "시설 관리",
  description: "시설 운영 상태 · AI 가능 원인 후보",
};

export default function FacilitiesPage() {
  return <FacilityManager />;
}
