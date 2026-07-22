import type { Metadata } from "next";
import { NoticeEditor } from "@/features/notices/NoticeEditor";

export const metadata: Metadata = {
  title: "새 공지 작성",
  description: "공지를 작성해 임시저장·예약·즉시 발행합니다.",
};

export default function NoticeNewPage() {
  return <NoticeEditor mode="create" />;
}
