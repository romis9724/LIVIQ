import type { Metadata } from "next";
import { NoticeBoard } from "@/features/notices/NoticeBoard";

export const metadata: Metadata = {
  title: "공지",
  description: "단지 공지 · 말머리 필터 · AI 요약",
};

export default function NoticesPage() {
  return <NoticeBoard />;
}
