import type { Metadata } from "next";
import { AiConfigPanel } from "@/features/ai-config/AiConfigPanel";

export const metadata: Metadata = {
  title: "AI 설정",
  description: "어시스턴트가 사용할 LLM 엔드포인트·모델·키를 설정하고 연결을 테스트합니다.",
};

export default function SystemAiPage() {
  return <AiConfigPanel />;
}
