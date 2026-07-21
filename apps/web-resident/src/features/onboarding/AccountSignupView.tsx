"use client";

import { useCallback, useEffect, useState } from "react";
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
  if (status === 404) return "선택한 단지를 찾을 수 없습니다. 다시 선택해 주세요.";
  if (status === 422) return "입력 형식을 확인해 주세요.";
  return "가입 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
}

interface TenantOption {
  id: string;
  name: string;
}

/**
 * 계정 가입 진입 — 단지 선택 + 이메일 + 비밀번호(ADR-0014 개정, H7-5).
 * 로그인 화면의 회원가입 버튼으로 진입하며, 단지 안내문의 가입 링크(?t={tenant_id})는
 * 단지를 사전 선택한다. 성공(201) 시 검증 메일 안내로 전환한다.
 */
export function AccountSignupView() {
  useRedirectIfAuthed();

  // undefined=로딩 · null=목록 조회 실패(재시도 버튼) · []=등록된 단지 없음.
  const [tenants, setTenants] = useState<TenantOption[] | null | undefined>(undefined);
  const [preselected, setPreselected] = useState<string | null>(null);

  const load = useCallback(async () => {
    setTenants(undefined);
    try {
      const res = await fetch(`${API_BASE_URL}/auth/tenants`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as { items: TenantOption[] };
      setTenants(body.items);
    } catch {
      setTenants(null);
    }
  }, []);

  useEffect(() => {
    // 가입 링크 ?t — SSR 불일치 회피 위해 마운트 후 URL에서 읽어 사전 선택만 한다.
    setPreselected(parseTenantId(new URLSearchParams(window.location.search).get("t")));
    void load();
  }, [load]);

  return (
    <main id="main" className="auth-shell">
      <div className="auth-inner">
        <div className="auth-brand auth-brand--sm">
          <span className="auth-brand__logo" aria-hidden="true">
            L
          </span>
          <span className="auth-brand__wordmark">LIVIQ</span>
        </div>

        {tenants === undefined ? (
          <p className="auth-hint" role="status">
            단지 목록을 불러오고 있어요…
          </p>
        ) : tenants === null ? (
          <section className="auth-status" aria-live="polite">
            <div className="auth-state-card">
              <div className="auth-state__icon" aria-hidden="true">
                ⚠️
              </div>
              <h1 className="auth-state__title">단지 목록을 불러오지 못했습니다</h1>
              <p className="auth-state__desc">네트워크 상태를 확인한 뒤 다시 시도해 주세요.</p>
              <Button type="button" variant="primary" onClick={() => void load()}>
                다시 시도
              </Button>
            </div>
          </section>
        ) : (
          <SignupForm tenants={tenants} preselected={preselected} />
        )}
      </div>
    </main>
  );
}

function SignupForm({
  tenants,
  preselected,
}: {
  tenants: TenantOption[];
  preselected: string | null;
}) {
  const router = useRouter();
  // 사전 선택(가입 링크)이 목록에 실제로 있을 때만 반영 — 삭제된 단지 링크 방어.
  const [tenantId, setTenantId] = useState(() =>
    preselected && tenants.some((t) => t.id === preselected) ? preselected : "",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [errors, setErrors] = useState<AccountSignupErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);

  const submit = async () => {
    const next = validateAccountSignup({ tenantId, email, password, passwordConfirm });
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
      <h1 className="auth-title auth-title--sm">회원가입</h1>
      <p className="auth-lede">
        단지를 선택하고 이메일로 가입하세요. 인증 메일 확인 후 입주민 정보를 입력하면 관리소장
        승인을 거쳐 이용할 수 있습니다.
      </p>

      <form
        className="auth-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        noValidate
      >
        <div className="auth-select auth-field">
          <label className="form-field__label" htmlFor="signup-tenant">
            단지
          </label>
          <select
            id="signup-tenant"
            className="auth-select__input"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            aria-invalid={errors.tenantId ? true : undefined}
            aria-describedby={errors.tenantId ? "signup-tenant-error" : undefined}
          >
            <option value="" disabled>
              거주하시는 단지를 선택해 주세요
            </option>
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
          {errors.tenantId ? (
            <div id="signup-tenant-error" className="form-field__error">
              {errors.tenantId}
            </div>
          ) : null}
        </div>
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
