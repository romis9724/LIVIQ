"use client";

import { useEffect, useState } from "react";
import { Button, FormField } from "@liviq/ui";
import { API_BASE_URL } from "@/lib/api";
import "./login.css";

// 이메일 형식·비밀번호 길이는 즉시 피드백 보조 — 최종 판정·역할 검증은 서버(ADR-0014).
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LENGTH = 10;

type Banner = "verified" | "verify_error" | null;

interface FieldErrors {
  email?: string;
  password?: string;
}

/** 로그인 상태 코드 → 한국어 안내. 401은 계정 존재를 노출하지 않는 단일 메시지. */
function loginErrorMessage(status: number): string {
  if (status === 401) return "이메일 또는 비밀번호가 올바르지 않습니다.";
  if (status === 403) return "이메일 인증을 완료해 주세요.";
  if (status === 429) return "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.";
  return "로그인 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
}

/** 관리자 로그인 — 이메일+비밀번호. 관리자 권한은 서버가 검증. 성공 시 루트(/)로 이동. */
export default function AdminLoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has("verified")) setBanner("verified");
    else if (params.has("verify_error")) setBanner("verify_error");
  }, []);

  const submit = async () => {
    const next: FieldErrors = {};
    if (!EMAIL_RE.test(email.trim())) next.email = "이메일 형식이 올바르지 않습니다.";
    if (password.length < MIN_PASSWORD_LENGTH)
      next.password = `비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`;

    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length > 0) return;

    setSubmitting(true);
    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      if (response.ok) {
        window.location.href = "/";
        return;
      }
      setFormError(loginErrorMessage(response.status));
    } catch {
      setFormError("로그인 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSubmitting(false);
    }
  };

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
          등록된 이메일로 로그인하세요. 관리자 권한은 서버에서 확인합니다.
        </p>

        {banner ? (
          <p
            className={
              banner === "verify_error"
                ? "admin-login__hint admin-login__hint--error"
                : "admin-login__hint"
            }
            role="status"
          >
            {banner === "verified"
              ? "이메일 인증이 완료되었습니다. 로그인해 주세요."
              : "인증 링크가 유효하지 않거나 만료되었습니다. 다시 시도해 주세요."}
          </p>
        ) : null}

        <form
          className="admin-login__form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          noValidate
        >
          <FormField
            label="이메일"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            inputMode="email"
            error={errors.email}
          />
          <FormField
            label="비밀번호"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            error={errors.password}
          />

          {formError ? (
            <p className="admin-login__hint admin-login__hint--error" role="alert">
              {formError}
            </p>
          ) : null}

          <Button
            type="submit"
            variant="primary"
            className="admin-login__submit"
            disabled={submitting}
          >
            {submitting ? "로그인 중…" : "로그인"}
          </Button>
        </form>
      </div>
    </main>
  );
}
