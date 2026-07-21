import type { Metadata } from "next";
import { ResetPasswordView } from "@/features/onboarding/ResetPasswordView";

export const metadata: Metadata = {
  title: "비밀번호 재설정",
  description: "가입한 이메일로 재설정 링크를 받거나 새 비밀번호를 설정합니다.",
};

export default function ResetPasswordPage() {
  return <ResetPasswordView />;
}
