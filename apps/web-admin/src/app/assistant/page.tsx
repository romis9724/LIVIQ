import type { Metadata } from "next";
import { AdminAssistant } from "@/features/assistant/AdminAssistant";

export const metadata: Metadata = {
  title: "AI 비서",
  description: "관리소 운영 질의응답 — 민원 현황 브리핑·시설·문서 근거 답변",
};

export default function AdminAssistantPage() {
  return <AdminAssistant />;
}
