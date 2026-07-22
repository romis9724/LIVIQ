import type { Metadata } from "next";
import { CodeRegistry } from "@/features/settings/CodeRegistry";

export const metadata: Metadata = {
  title: "코드 관리",
  description: "관리비 항목·시설 유형 등 공통 코드 그룹과 계층 코드를 관리합니다.",
};

export default function SettingsCodesPage() {
  return <CodeRegistry />;
}
