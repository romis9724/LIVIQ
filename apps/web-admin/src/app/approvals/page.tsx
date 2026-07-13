import type { Metadata } from "next";
import { Approvals } from "@/features/approvals/Approvals";

export const metadata: Metadata = {
  title: "가입 승인",
  description: "입주민 가입 신청을 명부와 대조해 승인·거절합니다.",
};

export default function ApprovalsPage() {
  return <Approvals />;
}
