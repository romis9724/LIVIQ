import type { Metadata } from "next";
import { AssistantChat } from "@/features/assistant/AssistantChat";

export const metadata: Metadata = {
  title: "AI 비서",
  description: "단지 규약·관리비·시설을 출처와 함께 답해드립니다.",
};

export default function AssistantPage() {
  return <AssistantChat />;
}
