import type { Metadata } from "next";
import { FeesAdmin } from "@/features/fee-upload/FeesAdmin";

export const metadata: Metadata = {
  title: "관리비 관리",
  description:
    "단지 총액 엑셀을 세대수로 균등분배해 동/호별로 조회·고지합니다. AI는 설명만, 계산·부과는 하지 않습니다.",
};

export default function FeesPage() {
  return <FeesAdmin />;
}
