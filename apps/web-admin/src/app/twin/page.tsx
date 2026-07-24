import type { Metadata } from "next";
import { TwinView } from "@/features/twin/TwinView";

export const metadata: Metadata = {
  title: "단지 트윈",
  description: "세대 3D 모형 + 세대원 수 오버레이",
};

export default function TwinPage() {
  return <TwinView />;
}
