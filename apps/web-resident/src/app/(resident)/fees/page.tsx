import type { Metadata } from "next";
import { FeesView } from "@/features/fees/FeesView";

export const metadata: Metadata = {
  title: "관리비",
  description: "이번 달 관리비 · 추이 · 항목 · 왜 올랐나 AI 설명",
};

export default function FeesPage() {
  return <FeesView />;
}
