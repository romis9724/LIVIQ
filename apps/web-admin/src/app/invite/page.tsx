"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button, FormField } from "@liviq/ui";
import { ApiError, acceptInvite } from "@/lib/api";
import "@/features/auth/auth.css";

// 비밀번호 길이는 즉시 피드백 보조 — 최종 판정은 서버(≥10자, ADR-0014).
const MIN_PASSWORD_LENGTH = 10;

interface FieldErrors {
  password?: string;
  confirm?: string;
}

/** 초대 수락 — 링크의 token + 새 비밀번호로 계정 활성화(H7-2). */
export default function InviteAcceptPage() {
  const [token, setToken] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("token");
    setToken(value);
  }, []);

  const submit = async () => {
    if (!token) return;
    const next: FieldErrors = {};
    if (password.length < MIN_PASSWORD_LENGTH)
      next.password = `비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`;
    if (confirm !== password) next.confirm = "비밀번호가 일치하지 않습니다.";

    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length > 0) return;

    setSubmitting(true);
    try {
      await acceptInvite(token, password);
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setFormError("링크가 만료되었거나 이미 사용되었습니다. 초대를 다시 요청해 주세요.");
      } else {
        setFormError("계정 활성화 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main id="main" className="auth-page">
      <div className="auth-card">
        <div className="auth-card__brand">
          <span className="auth-card__logo" aria-hidden="true">
            L
          </span>
          <span className="auth-card__wordmark">LIVIQ 관리자 콘솔</span>
        </div>

        {done ? (
          <div className="auth-card__done">
            <h1 className="auth-card__title">계정이 활성화되었습니다</h1>
            <p className="auth-card__lede">설정한 비밀번호로 로그인할 수 있습니다.</p>
            <Link className="auth-card__link" href="/login">
              로그인하러 가기 →
            </Link>
          </div>
        ) : token === null ? (
          <>
            <h1 className="auth-card__title">초대 링크 확인</h1>
            <p className="auth-card__hint auth-card__hint--error" role="alert">
              초대 토큰이 없습니다. 메일의 초대 링크로 다시 접속해 주세요.
            </p>
          </>
        ) : (
          <>
            <h1 className="auth-card__title">계정 비밀번호 설정</h1>
            <p className="auth-card__lede">
              비밀번호를 설정하면 계정이 활성화됩니다. 이후 이 이메일로 로그인하세요.
            </p>

            <form
              className="auth-card__form"
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
              noValidate
            >
              <FormField
                label="새 비밀번호"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                error={errors.password}
              />
              <FormField
                label="새 비밀번호 확인"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                error={errors.confirm}
              />

              {formError ? (
                <p className="auth-card__hint auth-card__hint--error" role="alert">
                  {formError}
                </p>
              ) : null}

              <Button
                type="submit"
                variant="primary"
                className="auth-card__submit"
                disabled={submitting}
              >
                {submitting ? "활성화 중…" : "계정 활성화"}
              </Button>
            </form>
          </>
        )}
      </div>
    </main>
  );
}
