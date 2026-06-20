import type { Metadata } from "next";
import { MeView } from "@/features/me/MeView";

export const metadata: Metadata = {
  title: "나",
  description: "활동 이력 · 설정 · 개인정보 동의",
};

export default function MePage() {
  return <MeView />;
}
