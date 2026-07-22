import type { Metadata } from "next";
import { HouseholdAdmin } from "@/features/settings/HouseholdAdmin";

export const metadata: Metadata = {
  title: "동/호수 관리",
  description: "단지의 동과 세대를 관리합니다.",
};

export default function SettingsHouseholdsPage() {
  return <HouseholdAdmin />;
}
