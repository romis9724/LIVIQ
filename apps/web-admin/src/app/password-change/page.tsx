"use client";

import { useState } from "react";
import { Button, FormField } from "@liviq/ui";
import { ApiError, changePassword } from "@/lib/api";
import "@/features/auth/auth.css";

// 비밀번호 길이는 즉시 피드백 보조 — 최종 판정은 서버(≥10자, ADR-0014).
const MIN_PASSWORD_LENGTH = 10;

interface FieldErrors {
  current?: string;
  next?: string;
  confirm?: string;
}

/** 비밀번호 변경 — 임시 비밀번호 강제 변경(must_change_password)과 자발적 변경 공용(H7-2). */
export default function PasswordChangePage() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    const fieldErrors: FieldErrors = {};
    if (current.length === 0) fieldErrors.current = "현재 비밀번호를 입력해 주세요.";
    if (next.length < MIN_PASSWORD_LENGTH)
      fieldErrors.next = `비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`;
    if (confirm !== next) fieldErrors.confirm = "비밀번호가 일치하지 않습니다.";

    setErrors(fieldErrors);
    setFormError(null);
    if (Object.keys(fieldErrors).length > 0) return;

    setSubmitting(true);
    try {
      await changePassword(current, next);
      // 세션 재발급 완료 — 홈으로(역할별 첫 진입은 AdminShell이 판단).
      window.location.href = "/";
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setErrors((prev) => ({ ...prev, current: "현재 비밀번호가 올바르지 않습니다." }));
      } else {
        setFormError("비밀번호 변경 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.");
      }
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

        <h1 className="auth-card__title">비밀번호 변경</h1>
        <p className="auth-card__lede">
          계속 진행하려면 새 비밀번호를 설정하세요. 임시 비밀번호로 로그인한 경우 변경이 필요합니다.
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
            label="현재 비밀번호"
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            error={errors.current}
          />
          <FormField
            label="새 비밀번호"
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
            error={errors.next}
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
            {submitting ? "변경 중…" : "비밀번호 변경"}
          </Button>
        </form>
      </div>
    </main>
  );
}
