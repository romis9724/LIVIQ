import type { Metadata } from "next";
import { FeeUpload } from "@/features/fee-upload/FeeUpload";

export const metadata: Metadata = {
  title: "관리비 관리",
  description: "관리비 엑셀 업로드(검증·미리보기·확정)와 부과 현황. AI는 설명만, 계산·부과는 하지 않습니다.",
};

export default function FeesPage() {
  return <FeeUpload />;
}
