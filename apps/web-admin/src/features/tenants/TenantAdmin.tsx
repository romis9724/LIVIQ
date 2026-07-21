"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, EmptyState, FormField, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  createTenant,
  inviteManager,
  listTenants,
  type Tenant,
} from "@/lib/api";
import "./tenants.css";

const TOAST_DURATION_MS = 3200;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type ToastState = { message: string; tone: ToastTone };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function TenantAdmin() {
  const [tenants, setTenants] = useState<Tenant[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | undefined>(undefined);
  const [creating, setCreating] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const load = useCallback(async () => {
    try {
      setTenants(await listTenants());
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
      setTenants([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  async function submitCreate() {
    const trimmed = name.trim();
    if (trimmed.length === 0) {
      setNameError("단지 이름을 입력해 주세요.");
      return;
    }
    setNameError(undefined);
    setCreating(true);
    try {
      await createTenant(trimmed);
      setName("");
      await load(); // created_at 확보 위해 재조회
      showToast(`단지 "${trimmed}"를 생성했습니다.`);
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          단지 관리
        </h1>
        <p className="admin-page__lede">
          단지를 생성하고 각 단지에 소장을 초대합니다. 초대 메일의 링크로 소장이 비밀번호를 설정하면
          계정이 활성화됩니다.
        </p>
      </header>

      <main className="admin-page__main">
        <section className="surface-card tn-create" aria-labelledby="tn-create-h">
          <h2 id="tn-create-h" className="tn-section__title">
            단지 생성
          </h2>
          <form
            className="tn-create__form"
            onSubmit={(e) => {
              e.preventDefault();
              void submitCreate();
            }}
            noValidate
          >
            <FormField
              label="단지 이름"
              value={name}
              onChange={(e) => setName(e.target.value)}
              error={nameError}
              placeholder="예: 리비크 1단지"
              wrapperClassName="tn-create__field"
            />
            <Button type="submit" variant="primary" disabled={creating}>
              {creating ? "생성 중…" : "단지 생성"}
            </Button>
          </form>
        </section>

        <section className="tn-list" aria-labelledby="tn-list-h">
          <h2 id="tn-list-h" className="tn-section__title">
            단지 목록
          </h2>

          {loadError ? (
            <EmptyState icon="⚠" title="목록을 불러오지 못했습니다" description={loadError} />
          ) : tenants === null ? (
            <div className="tn-rows">
              <Skeleton height="88px" />
              <Skeleton height="88px" />
            </div>
          ) : tenants.length === 0 ? (
            <EmptyState
              icon="🏘"
              title="아직 생성된 단지가 없습니다"
              description="위에서 첫 단지를 생성해 보세요."
            />
          ) : (
            <ul className="tn-rows">
              {tenants.map((tenant) => (
                <TenantRow
                  key={tenant.id}
                  tenant={tenant}
                  onInvited={(msg) => showToast(msg)}
                  onError={(msg) => showToast(msg, "danger")}
                />
              ))}
            </ul>
          )}
        </section>
      </main>

      {toast ? (
        <div className="tn-toast">
          <Toast tone={toast.tone} message={toast.message} />
        </div>
      ) : null}
    </>
  );
}

interface TenantRowProps {
  tenant: Tenant;
  onInvited: (message: string) => void;
  onError: (message: string) => void;
}

function TenantRow({ tenant, onInvited, onError }: TenantRowProps) {
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);

  async function invite() {
    const trimmed = email.trim();
    if (!EMAIL_RE.test(trimmed)) {
      setEmailError("이메일 형식이 올바르지 않습니다.");
      return;
    }
    setEmailError(undefined);
    setBusy(true);
    try {
      await inviteManager(tenant.id, trimmed);
      setEmail("");
      onInvited(`${trimmed} 앞으로 소장 초대 메일을 발송했습니다.`);
    } catch (err) {
      onError(err instanceof ApiError || err instanceof Error ? err.message : "초대에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="tn-row">
      <div className="tn-row__head">
        <span className="tn-row__name">{tenant.name}</span>
        <span className="tn-row__date">생성 {tenant.createdAt.slice(0, 10)}</span>
      </div>
      <form
        className="tn-invite"
        onSubmit={(e) => {
          e.preventDefault();
          void invite();
        }}
        noValidate
      >
        <FormField
          label="소장 초대 이메일"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={emailError}
          autoComplete="off"
          inputMode="email"
          placeholder="manager@example.com"
          wrapperClassName="tn-invite__field"
        />
        <Button type="submit" variant="secondary" size="sm" disabled={busy}>
          {busy ? "발송 중…" : "소장 초대"}
        </Button>
      </form>
    </li>
  );
}
