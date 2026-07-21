import type { Metadata } from "next";
import { StaffAdmin } from "@/features/staff/StaffAdmin";

export const metadata: Metadata = {
  title: "직원 관리",
  description: "단지 직원을 초대하고 관리합니다.",
};

export default function StaffPage() {
  return <StaffAdmin />;
}
