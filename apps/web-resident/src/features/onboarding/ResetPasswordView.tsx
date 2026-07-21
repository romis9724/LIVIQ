"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button, FormField } from "@liviq/ui";
import { API_BASE_URL } from "@/lib/dev-context";
import { isValidEmail, validateNewPassword, type NewPasswordErrors } from "./logic";
import "./onboarding.css";

/**
 * 비밀번호 재설정 — 한 페이지 두 상태(ADR-0014).
 * ?token 없음: 이메일로 재설정 링크 요청(존재 비노출 — 항상 성공 카피).
 * ?token 있음: 새 비밀번호 설정 → 완료 후 로그인.
 */
export function ResetPasswordView() {
  // undefined=파싱 전(SSR 불일치 회피) · null=요청 모드 · string=확인 모드.
  const [token, setToken] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("token");
    setToken(raw && raw.trim() ? raw : null);
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

        {token === undefined ? (
          <p className="auth-hint" role="status">
            불러오는 중…
          </p>
        ) : token === null ? (
          <RequestForm />
        ) : (
          <ConfirmForm token={token} />
        )}
      </div>
    </main>
  );
}

function RequestForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async () => {
    if (!isValidEmail(email)) {
      setError("이메일 형식이 올바르지 않습니다.");
      return;
    }
    setError(undefined);
    setFormError(null);
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/auth/password-reset`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
      // 존재 비노출 — 202 는 항상 성공 카피. 429(과다 요청)만 별도 안내.
      if (res.status === 429) {
        setFormError("요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.");
        return;
      }
      setSent(true);
    } catch {
      setFormError("요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSubmitting(false);
    }
  };

  if (sent) {
    return (
      <section className="auth-status" aria-live="polite">
        <div className="auth-state-card">
          <div className="auth-state__icon" aria-hidden="true">
            📮
          </div>
          <h1 className="auth-state__title">재설정 링크를 보냈습니다</h1>
          <p className="auth-state__desc">
            가입된 이메일인 경우 재설정 링크를 보냈습니다. 받은편지함을 확인해 링크를 열어 주세요.
          </p>
          <Link className="auth-consent__view" href="/login">
            로그인 화면으로
          </Link>
        </div>
      </section>
    );
  }

  return (
    <>
      <h1 className="auth-title auth-title--sm">비밀번호 재설정</h1>
      <p className="auth-lede">가입한 이메일을 입력하면 재설정 링크를 보내드립니다.</p>

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
          error={error}
          wrapperClassName="auth-field"
        />

        {formError ? (
          <p className="auth-hint auth-hint--error" role="alert">
            {formError}
          </p>
        ) : null}

        <Button type="submit" variant="primary" className="auth-submit" disabled={submitting}>
          {submitting ? "전송 중…" : "재설정 링크 받기"}
        </Button>
      </form>

      <p className="auth-foot">
        <Link className="auth-consent__view" href="/login">
          로그인으로 돌아가기
        </Link>
      </p>
    </>
  );
}

function ConfirmForm({ token }: { token: string }) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [errors, setErrors] = useState<NewPasswordErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [expired, setExpired] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async () => {
    const next = validateNewPassword(password, passwordConfirm);
    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length > 0) return;

    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/auth/password-reset/confirm`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      if (res.status === 204) {
        setDone(true);
        return;
      }
      if (res.status === 400) {
        setExpired(true);
        return;
      }
      setFormError("변경 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.");
    } catch {
      setFormError("변경 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <section className="auth-status" aria-live="polite">
        <div className="auth-state-card">
          <div className="auth-state__icon" aria-hidden="true">
            ✅
          </div>
          <h1 className="auth-state__title">비밀번호가 변경되었습니다</h1>
          <p className="auth-state__desc">새 비밀번호로 로그인해 주세요.</p>
          <Button
            type="button"
            variant="primary"
            className="auth-submit"
            onClick={() => router.push("/login")}
          >
            로그인하기
          </Button>
        </div>
      </section>
    );
  }

  if (expired) {
    return (
      <section className="auth-status" aria-live="polite">
        <div className="auth-state-card">
          <div className="auth-state__icon auth-state__icon--danger" aria-hidden="true">
            ⚠
          </div>
          <h1 className="auth-state__title">링크가 만료되었어요</h1>
          <p className="auth-state__desc">
            링크가 만료되었거나 이미 사용되었습니다. 재설정을 다시 요청해 주세요.
          </p>
          <Link className="auth-consent__view" href="/reset-password">
            재설정 다시 요청하기
          </Link>
        </div>
      </section>
    );
  }

  return (
    <>
      <h1 className="auth-title auth-title--sm">새 비밀번호 설정</h1>

      <form
        className="auth-form"
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
          help="10자 이상 입력해 주세요."
          error={errors.password}
          wrapperClassName="auth-field"
        />
        <FormField
          label="새 비밀번호 확인"
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
          {submitting ? "변경 중…" : "비밀번호 변경"}
        </Button>
      </form>
    </>
  );
}
