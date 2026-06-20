import type { Metadata } from "next";
import { InquiryCenter } from "@/features/inquiries/InquiryCenter";

export const metadata: Metadata = {
  title: "민원·하자",
  description: "사진과 함께 접수 · AI 분류 · 처리 타임라인",
};

export default function InquiriesPage() {
  return <InquiryCenter />;
}
