import type { Metadata } from "next";
import { SignupView } from "@/features/onboarding/SignupView";

// OAuth 콜백은 신규 계정을 /onboarding 으로 되돌린다(auth.py _ONBOARDING_PATH).
// 가입 화면(/signup)과 동일 뷰 — 콜백 복귀 경로와 앱 라우트를 정합시키는 별칭.
export const metadata: Metadata = {
  title: "가입 신청",
  description: "약관 동의 후 입주민 정보를 입력하고 가입을 신청합니다.",
};

export default function OnboardingPage() {
  return <SignupView />;
}
