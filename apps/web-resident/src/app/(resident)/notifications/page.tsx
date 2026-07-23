import type { Metadata } from "next";

import { NotificationsView } from "@/features/me/NotificationsView";

export const metadata: Metadata = {
  title: "알림",
  description: "공지 · 민원 상태 · 검수 결과 인앱 알림 전체 목록",
};

export default function NotificationsPage() {
  return <NotificationsView />;
}
