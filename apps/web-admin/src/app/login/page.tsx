"use client";

import { Button } from "@liviq/ui";
import { API_BASE_URL } from "@/lib/api";
import "./login.css";

/** 관리자 로그인 — 구글 OAuth(PKCE). 콜백이 세션 확립 후 복귀. 관리자 역할은 서버가 검증. */
export default function AdminLoginPage() {
  return (
    <main id="main" className="admin-login">
      <div className="admin-login__card">
        <div className="admin-login__brand">
          <span className="admin-login__logo" aria-hidden="true">
            L
          </span>
          <span className="admin-login__wordmark">LIVIQ 관리자 콘솔</span>
        </div>
        <h1 className="admin-login__title">관리사무소 로그인</h1>
        <p className="admin-login__lede">
          구글 계정으로 로그인하세요. 관리자 권한은 서버에서 확인합니다.
        </p>
        <Button
          type="button"
          variant="primary"
          className="admin-login__google"
          onClick={() => {
            window.location.href = `${API_BASE_URL}/auth/google/login`;
          }}
        >
          <span className="admin-login__mark" aria-hidden="true">
            G
          </span>
          Google로 로그인
        </Button>
      </div>
    </main>
  );
}
