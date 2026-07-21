"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button, FormField } from "@liviq/ui";
import { API_BASE_URL } from "@/lib/dev-context";
import { MIN_PASSWORD_LENGTH, isValidEmail } from "./logic";
import { useRedirectIfAuthed } from "./useRedirectIfAuthed";
import "./onboarding.css";

/** 검증 링크 복귀 배너. verified=인증 완료, verify_error=링크 무효/만료. */
type Banner = "verified" | "verify_error" | null;

interface FieldErrors {
  email?: string;
  password?: string;
}

/** 로그인 상태 코드 → 한국어 안내. 401은 계정 존재를 노출하지 않는 단일 메시지(규칙 4). */
function loginErrorMessage(status: number): string {
  if (status === 401) return "이메일 또는 비밀번호가 올바르지 않습니다.";
  if (status === 403) return "이메일 인증을 완료해 주세요.";
  if (status === 429) return "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.";
  return "로그인 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
}

/** 로그인 진입 — 이메일+비밀번호. 성공 시 루트(/)가 /me 상태로 화면을 분기한다. */
export function LoginView() {
  useRedirectIfAuthed();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  useEffect(() => {
    // 검증 링크 복귀 쿼리 — SSR 불일치 회피 위해 마운트 후 URL에서 읽는다.
    const params = new URLSearchParams(window.location.search);
    if (params.has("verified")) setBanner("verified");
    else if (params.has("verify_error")) setBanner("verify_error");
  }, []);

  const submit = async () => {
    const next: FieldErrors = {};
    if (!isValidEmail(email)) next.email = "이메일 형식이 올바르지 않습니다.";
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
    <main id="main" className="auth-shell">
      <div className="auth-inner">
        <div className="auth-brand auth-brand--sm">
          <span className="auth-brand__logo" aria-hidden="true">
            L
          </span>
          <span className="auth-brand__wordmark">LIVIQ</span>
        </div>
        <h1 className="auth-title auth-title--sm">우리 단지 AI 생활 비서</h1>
        <p className="auth-lede">
          공지·관리비·민원을 출처와 함께 물어보세요. 관리사무소가 확인한 정보만 답합니다.
        </p>

        {banner ? (
          <p
            className={banner === "verify_error" ? "auth-hint auth-hint--error" : "auth-hint"}
            role="status"
          >
            {banner === "verified"
              ? "이메일 인증이 완료되었습니다. 로그인해 주세요."
              : "인증 링크가 유효하지 않거나 만료되었습니다. 다시 시도해 주세요."}
          </p>
        ) : null}

        <form
          className="auth-form"
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
            wrapperClassName="auth-field"
          />
          <FormField
            label="비밀번호"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            error={errors.password}
            wrapperClassName="auth-field"
          />

          {formError ? (
            <p className="auth-hint auth-hint--error" role="alert">
              {formError}
            </p>
          ) : null}

          <Button type="submit" variant="primary" className="auth-submit" disabled={submitting}>
            {submitting ? "로그인 중…" : "로그인"}
          </Button>

          <Link className="auth-consent__view auth-forgot" href="/reset-password">
            비밀번호를 잊으셨나요?
          </Link>
        </form>

        <p className="auth-foot">
          처음이신가요? 단지 안내문의 가입 링크로 가입하세요.
        </p>
        <p className="auth-foot">
          <span aria-hidden="true">🔒</span> 가입 후 관리소장 승인이 필요합니다.
        </p>
      </div>
    </main>
  );
}
