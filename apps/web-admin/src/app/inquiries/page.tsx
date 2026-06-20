import type { Metadata } from "next";
import { InquiryAdmin } from "@/features/inquiry-admin/InquiryAdmin";

export const metadata: Metadata = {
  title: "민원 관리",
  description: "AI 분류·우선순위 제안 · 담당자 배정",
};

export default function InquiriesAdminPage() {
  return <InquiryAdmin />;
}
