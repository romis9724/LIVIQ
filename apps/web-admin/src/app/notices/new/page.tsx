import type { Metadata } from "next";
import { NoticeComposer } from "@/features/notice-composer/NoticeComposer";

export const metadata: Metadata = {
  title: "공지 초안 작성",
  description: "키워드에서 AI 초안을 만들고 검수 후 발송합니다. 자동 발송은 없습니다.",
};

export default function NoticeNewPage() {
  return <NoticeComposer />;
}
