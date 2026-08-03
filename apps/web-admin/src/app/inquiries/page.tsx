import type { Metadata } from "next";
import { Suspense } from "react";
import { InquiryAdmin } from "@/features/inquiry-admin/InquiryAdmin";

export const metadata: Metadata = {
  title: "민원 관리",
  description: "AI 분류·우선순위 제안 · 담당자 배정",
};

export default function InquiriesAdminPage() {
  // InquiryAdmin 이 useSearchParams(?inquiry= 딥링크)를 쓴다 — App Router 는 Suspense 경계 필수.
  return (
    <Suspense>
      <InquiryAdmin />
    </Suspense>
  );
}
