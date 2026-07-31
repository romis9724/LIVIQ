import type { Metadata } from "next";
import { Suspense } from "react";
import { InquiryCenter } from "@/features/inquiries/InquiryCenter";

export const metadata: Metadata = {
  title: "민원·하자",
  description: "사진과 함께 접수 · AI 분류 · 처리 타임라인",
};

export default function InquiriesPage() {
  // InquiryCenter 가 useSearchParams(접수 딥링크 프리필)를 쓴다 — App Router 는 Suspense 경계 필수.
  return (
    <Suspense>
      <InquiryCenter />
    </Suspense>
  );
}
