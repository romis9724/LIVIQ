import type { Metadata } from "next";
import { ParkingView } from "@/features/parking/ParkingView";

export const metadata: Metadata = {
  title: "주차장 대시보드",
  description: "지하주차장 배치도 · 입주민/외부 차량 현황(점유는 시뮬레이션)",
};

export default function ParkingPage() {
  return <ParkingView />;
}
