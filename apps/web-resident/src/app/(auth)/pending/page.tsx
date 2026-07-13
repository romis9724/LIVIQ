import type { Metadata } from "next";
import { PendingView } from "@/features/onboarding/PendingView";

export const metadata: Metadata = {
  title: "계정 상태",
  description: "가입 승인 대기·반려·비활성 계정 상태 안내.",
};

export default function PendingPage() {
  return <PendingView />;
}
