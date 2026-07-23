import { Suspense } from "react";
import type { Metadata } from "next";
import { NoticeBoard } from "@/features/notices/NoticeBoard";

export const metadata: Metadata = {
  title: "공지",
  description: "단지 공지 · 말머리 필터 · AI 요약",
};

export default function NoticesPage() {
  // NoticeBoard 가 useSearchParams(?id=) 를 쓰므로 Suspense 경계 필요(App Router 프리렌더).
  return (
    <Suspense fallback={null}>
      <NoticeBoard />
    </Suspense>
  );
}
