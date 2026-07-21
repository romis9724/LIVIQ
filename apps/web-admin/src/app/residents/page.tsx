import type { Metadata } from "next";
import { Residents } from "@/features/residents/Residents";

export const metadata: Metadata = {
  title: "주민 관리",
  description: "단지 명부를 관리하고 가입 신청을 승인·거절합니다.",
};

export default function ResidentsPage() {
  return <Residents />;
}
