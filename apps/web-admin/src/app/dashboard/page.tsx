import type { Metadata } from "next";
import { Dashboard } from "@/features/dashboard/Dashboard";

export const metadata: Metadata = {
  title: "대시보드",
  description: "자동해결률 · 환각률 · 토큰 비용 · 민원 현황",
};

export default function DashboardPage() {
  return <Dashboard />;
}
