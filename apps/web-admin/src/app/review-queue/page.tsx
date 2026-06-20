import type { Metadata } from "next";
import { ReviewQueue } from "@/features/review-queue/ReviewQueue";

export const metadata: Metadata = {
  title: "AI 검수 큐",
  description: "신뢰도가 낮은 AI 답변을 검토하고 승인·반려합니다.",
};

export default function ReviewQueuePage() {
  return <ReviewQueue />;
}
