import type { Metadata } from "next";
import { LoginView } from "@/features/onboarding/LoginView";

export const metadata: Metadata = {
  title: "로그인",
  description: "우리 단지 AI 생활 비서 LIVIQ 시작하기.",
};

export default function LoginPage() {
  return <LoginView />;
}
