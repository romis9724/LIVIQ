"use client";

import { useRouter } from "next/navigation";
import { Button } from "@liviq/ui";
import "./onboarding.css";

/** 로그인 진입 — 구글 OAuth 목업. 클릭 시 가입 플로우로 이동. */
export function LoginView() {
  const router = useRouter();

  return (
    <main id="main" className="auth-shell">
      <div className="auth-inner auth-inner--center">
        <div className="auth-brand">
          <span className="auth-brand__logo" aria-hidden="true">
            L
          </span>
          <span className="auth-brand__wordmark">LIVIQ</span>
        </div>
        <h1 className="auth-title">우리 단지 AI 생활 비서</h1>
        <p className="auth-lede">
          공지·관리비·민원을 출처와 함께 물어보세요. 관리사무소가 확인한 정보만 답합니다.
        </p>

        <Button
          type="button"
          variant="secondary"
          className="auth-google"
          onClick={() => router.push("/signup")}
        >
          <span className="auth-google__mark" aria-hidden="true">
            G
          </span>
          Google로 시작하기
        </Button>

        <p className="auth-foot">
          <span aria-hidden="true">🔒</span> 가입 후 관리소장 승인이 필요합니다.
        </p>
      </div>
    </main>
  );
}
