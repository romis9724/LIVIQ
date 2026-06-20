import type { Metadata } from "next";
import { MeetingMinutes } from "@/features/meetings/MeetingMinutes";

export const metadata: Metadata = {
  title: "회의록",
  description: "음성 STT → 요약·결정·액션아이템 → 검수 확정",
};

export default function MeetingsPage() {
  return <MeetingMinutes />;
}
