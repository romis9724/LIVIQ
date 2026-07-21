"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button, FormField } from "@liviq/ui";
import { API_BASE_URL } from "@/lib/dev-context";
import {
  parseTenantId,
  validateAccountSignup,
  type AccountSignupErrors,
} from "./logic";
import { useRedirectIfAuthed } from "./useRedirectIfAuthed";
import "./onboarding.css";

/** 가입 상태 코드 → 폼 상단 안내. 필드 오류는 별도. */
function signupErrorMessage(status: number): string {
  if (status === 409) return "이미 가입된 이메일입니다. 아래에서 로그인해 주세요.";
  if (status === 404) return "가입 링크가 유효하지 않습니다. 관리사무소에 문의해 주세요.";
  if (status === 422) return "입력 형식을 확인해 주세요.";
  return "가입 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
}

/**
 * 계정 가입 진입 — 단지별 가입 링크(?t={tenant_id})로 접속해 이메일+비밀번호로 계정을 만든다.
 * t 가 없거나 형식이 아니면 폼 대신 안내 화면. 성공(201) 시 검증 메일 안내로 전환한다(ADR-0014).
 */
export function AccountSignupView() {
  useRedirectIfAuthed();

  // undefined=파싱 전(SSR 불일치 회피) · null=링크 오류 · string=유효 단지.
  const [tenantId, setTenantId] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setTenantId(parseTenantId(params.get("t")));
  }, []);

  return (
    <main id="main" className="auth-shell">
      <div className="auth-inner">
        <div className="auth-brand auth-brand--sm">
          <span className="auth-brand__logo" aria-hidden="true">
            L
          </span>
          <span className="auth-brand__wordmark">LIVIQ</span>
        </div>

        {tenantId === undefined ? (
          <p className="auth-hint" role="status">
            가입 링크를 확인하고 있어요…
          </p>
        ) : tenantId === null ? (
          <InvalidLink />
        ) : (
          <SignupForm tenantId={tenantId} />
        )}
      </div>
    </main>
  );
}

function InvalidLink() {
  return (
    <section className="auth-status" aria-live="polite">
      <div className="auth-state-card">
        <div className="auth-state__icon" aria-hidden="true">
          🔗
        </div>
        <h1 className="auth-state__title">가입 링크로 접속해 주세요</h1>
        <p className="auth-state__desc">
          단지에서 안내받은 가입 링크(QR·URL)로 접속해야 가입할 수 있습니다. 관리사무소 게시물을
          확인해 주세요.
        </p>
        <p className="auth-hint">
          이미 계정이 있으신가요?{" "}
          <Link className="auth-consent__view" href="/login">
            로그인
          </Link>
        </p>
      </div>
    </section>
  );
}

function SignupForm({ tenantId }: { tenantId: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [errors, setErrors] = useState<AccountSignupErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);

  const submit = async () => {
    const next = validateAccountSignup({ email, password, passwordConfirm });
    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length > 0) return;

    const trimmed = email.trim();
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/auth/signup`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenantId, email: trimmed, password }),
      });
      if (res.status === 201) {
        setSentTo(trimmed);
        return;
      }
      setFormError(signupErrorMessage(res.status));
    } catch {
      setFormError("가입 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSubmitting(false);
    }
  };

  if (sentTo) {
    return (
      <section className="auth-status" aria-live="polite">
        <div className="auth-state-card">
          <div className="auth-state__icon" aria-hidden="true">
            📮
          </div>
          <h1 className="auth-state__title">인증 메일을 보냈습니다</h1>
          <p className="auth-state__desc">
            <strong>{sentTo}</strong> 받은편지함에서 링크를 열어 이메일 인증을 완료해 주세요. 인증
            후 로그인하면 입주민 정보를 입력할 수 있습니다.
          </p>
          <Button
            type="button"
            variant="primary"
            className="auth-submit"
            onClick={() => router.push("/login")}
          >
            로그인 화면으로
          </Button>
        </div>
      </section>
    );
  }

  return (
    <>
      <h1 className="auth-title auth-title--sm">계정을 만들어 주세요</h1>
      <p className="auth-lede">
        이메일로 가입한 뒤 인증 메일을 확인하면 입주민 정보를 입력할 수 있습니다.
      </p>

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
          autoComplete="new-password"
          help="10자 이상 입력해 주세요."
          error={errors.password}
          wrapperClassName="auth-field"
        />
        <FormField
          label="비밀번호 확인"
          type="password"
          value={passwordConfirm}
          onChange={(e) => setPasswordConfirm(e.target.value)}
          autoComplete="new-password"
          error={errors.passwordConfirm}
          wrapperClassName="auth-field"
        />

        {formError ? (
          <p className="auth-hint auth-hint--error" role="alert">
            {formError}
          </p>
        ) : null}

        <Button type="submit" variant="primary" className="auth-submit" disabled={submitting}>
          {submitting ? "가입 중…" : "가입하기"}
        </Button>
      </form>

      <p className="auth-foot">
        이미 계정이 있으신가요?{" "}
        <Link className="auth-consent__view" href="/login">
          로그인
        </Link>
      </p>
    </>
  );
}
