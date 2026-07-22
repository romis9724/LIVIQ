import type { Metadata } from "next";
import { NoticeEditor } from "@/features/notices/NoticeEditor";

export const metadata: Metadata = {
  title: "공지 수정",
  description: "공지 내용·상태·첨부를 관리합니다.",
};

export default async function NoticeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <NoticeEditor mode="edit" noticeId={id} />;
}
