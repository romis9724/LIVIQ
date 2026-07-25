import type { Metadata } from "next";
import { TwinView } from "@/features/twin/TwinView";

export const metadata: Metadata = {
  title: "트윈 대시보드",
  description: "세대 3D 모형 + 현황 + 상태 오버레이",
};

export default function TwinPage() {
  return <TwinView />;
}
