import type { Metadata } from "next";
import { HomeView } from "@/features/home/HomeView";

export const metadata: Metadata = {
  title: "홈",
  description: "단지 요약 · 관리비 · 공지 · 바로가기",
};

export default function HomePage() {
  return <HomeView />;
}
