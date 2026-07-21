import type { Metadata } from "next";
import { AccountSignupView } from "@/features/onboarding/AccountSignupView";

export const metadata: Metadata = {
  title: "계정 가입",
  description: "단지 가입 링크로 접속해 이메일과 비밀번호로 계정을 만듭니다.",
};

export default function SignupPage() {
  return <AccountSignupView />;
}
