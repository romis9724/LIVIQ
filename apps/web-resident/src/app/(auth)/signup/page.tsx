import type { Metadata } from "next";
import { SignupView } from "@/features/onboarding/SignupView";

export const metadata: Metadata = {
  title: "가입 신청",
  description: "약관 동의 후 입주민 정보를 입력하고 가입을 신청합니다.",
};

export default function SignupPage() {
  return <SignupView />;
}
