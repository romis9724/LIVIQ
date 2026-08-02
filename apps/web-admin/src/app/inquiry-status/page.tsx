import type { Metadata } from "next";
import { InquiryStatus } from "@/features/inquiry-status/InquiryStatus";

export const metadata: Metadata = {
  title: "민원현황",
  description: "오늘 할 일 · 민원 현황 · 시설 상태 · 일일 토큰 예산",
};

export default function InquiryStatusPage() {
  return <InquiryStatus />;
}
