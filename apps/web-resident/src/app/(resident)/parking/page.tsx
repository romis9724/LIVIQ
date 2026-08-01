import type { Metadata } from "next";
import { Suspense } from "react";
import { ParkingMapView } from "@/features/parking/ParkingMapView";

export const metadata: Metadata = {
  title: "주차장",
  description: "빈자리 · 내 차 위치 · AI 비서 추천 자리",
};

export default function ParkingPage() {
  // ParkingMapView 가 useSearchParams(?spot= 추천 면 딥링크)를 쓴다 — App Router 는 Suspense 경계 필수.
  return (
    <Suspense>
      <ParkingMapView />
    </Suspense>
  );
}
