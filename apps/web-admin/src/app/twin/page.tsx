import type { Metadata } from "next";
import { Suspense } from "react";
import { TwinView } from "@/features/twin/TwinView";

export const metadata: Metadata = {
  title: "트윈 대시보드",
  description: "세대 3D 모형 + 현황 + 상태 오버레이",
};

export default function TwinPage() {
  // TwinView 가 useSearchParams(?dong=&ho=&device= AI 비서 딥링크)를 쓴다 — Suspense 경계 필수.
  return (
    <Suspense>
      <TwinView />
    </Suspense>
  );
}
