import type { Metadata } from "next";
import { SignupView } from "@/features/onboarding/SignupView";

// 이메일 인증·로그인 후 registered 사용자가 도달하는 입주민 정보 입력 단계(ADR-0014).
// 계정 생성(이메일+비밀번호)은 /signup, 여기서는 프로필(성함·생년월일·동·호·동의)만 받는다.
export const metadata: Metadata = {
  title: "입주민 정보 입력",
  description: "약관 동의 후 입주민 정보를 입력하고 가입을 신청합니다.",
};

export default function OnboardingPage() {
  return <SignupView />;
}
