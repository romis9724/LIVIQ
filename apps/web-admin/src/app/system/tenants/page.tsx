import type { Metadata } from "next";
import { TenantAdmin } from "@/features/tenants/TenantAdmin";

export const metadata: Metadata = {
  title: "단지 관리",
  description: "단지를 생성하고 각 단지에 소장을 초대합니다.",
};

export default function TenantsPage() {
  return <TenantAdmin />;
}
