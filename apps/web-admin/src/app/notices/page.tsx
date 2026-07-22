import type { Metadata } from "next";
import { NoticeBoard } from "@/features/notices/NoticeBoard";

export const metadata: Metadata = {
  title: "공지사항",
  description: "공지 작성 · 임시저장 · 예약/즉시 발행",
};

export default function NoticesPage() {
  return <NoticeBoard />;
}
