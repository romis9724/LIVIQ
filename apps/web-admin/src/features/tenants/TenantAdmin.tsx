"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Dialog, EmptyState, FormField, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  createTenant,
  deleteTenant,
  inviteManager,
  listTenants,
  removeTenantManager,
  setTenantActive,
  type Tenant,
} from "@/lib/api";
import "./tenants.css";

const TOAST_DURATION_MS = 3200;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const MANAGER_STATUS_LABEL: Record<string, string> = {
  invited: "수락 대기",
  active: "활동 중",
  inactive: "비활성",
};

type ToastState = { message: string; tone: ToastTone };
type Confirm =
  | { kind: "removeManager"; tenant: Tenant }
  | { kind: "deleteTenant"; tenant: Tenant }
  | { kind: "deactivate"; tenant: Tenant };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

/** 확인 다이얼로그 문구 — 파괴적 작업별로 결과를 명시한다(H7-6). */
function confirmCopy(confirm: Confirm): { title: string; description: string; label: string } {
  const name = confirm.tenant.name;
  switch (confirm.kind) {
    case "removeManager":
      return {
        title: "소장을 제거할까요?",
        description: `"${name}"의 현재 소장 계정을 삭제합니다. 개인정보가 비식별 처리되고 복구할 수 없습니다. 제거 후 새 소장을 초대할 수 있습니다.`,
        label: "소장 제거",
      };
    case "deleteTenant":
      return {
        title: "단지를 삭제할까요?",
        description: `"${name}"을(를) 완전히 삭제합니다. 계정이나 데이터가 있는 단지는 삭제할 수 없습니다(운영 중 단지는 비활성화를 사용하세요).`,
        label: "단지 삭제",
      };
    case "deactivate":
      return {
        title: "단지를 비활성화할까요?",
        description: `"${name}" 소속 전 계정의 로그인이 차단되고 진행 중인 세션이 즉시 종료됩니다. 가입 단지 목록에서도 제외됩니다. 언제든 재활성화할 수 있습니다.`,
        label: "비활성화",
      };
  }
}

export function TenantAdmin() {
  const [tenants, setTenants] = useState<Tenant[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | undefined>(undefined);
  const [creating, setCreating] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
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

  /** 파괴적 작업 실행 — 다이얼로그 확인 후 호출. */
  async function runConfirmed() {
    if (!confirm) return;
    const { kind, tenant } = confirm;
    setBusyId(tenant.id);
    try {
      if (kind === "removeManager") {
        await removeTenantManager(tenant.id);
        showToast("소장을 제거했습니다. 새 소장을 초대해 주세요.", "neutral");
      } else if (kind === "deleteTenant") {
        await deleteTenant(tenant.id);
        showToast(`단지 "${tenant.name}"를 삭제했습니다.`, "neutral");
      } else {
        await setTenantActive(tenant.id, false);
        showToast("단지를 비활성화했습니다. 소속 계정 로그인이 차단됩니다.", "neutral");
      }
      setConfirm(null);
      await load();
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  async function reactivate(tenant: Tenant) {
    setBusyId(tenant.id);
    try {
      await setTenantActive(tenant.id, true);
      await load();
      showToast(`단지 "${tenant.name}"를 재활성화했습니다.`);
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  const copy = confirm ? confirmCopy(confirm) : null;

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          단지 관리
        </h1>
        <p className="admin-page__lede">
          단지를 생성하고 각 단지에 소장을 초대합니다(단지당 1명). 초대 메일의 링크로 소장이
          비밀번호를 설정하면 계정이 활성화됩니다.
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
              <Skeleton height="120px" />
              <Skeleton height="120px" />
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
                  busy={busyId === tenant.id}
                  onInvited={(msg) => {
                    showToast(msg);
                    void load();
                  }}
                  onError={(msg) => showToast(msg, "danger")}
                  onRemoveManager={() => setConfirm({ kind: "removeManager", tenant })}
                  onDeactivate={() => setConfirm({ kind: "deactivate", tenant })}
                  onActivate={() => void reactivate(tenant)}
                  onDelete={() => setConfirm({ kind: "deleteTenant", tenant })}
                />
              ))}
            </ul>
          )}
        </section>
      </main>

      <Dialog
        open={confirm !== null}
        title={copy?.title ?? ""}
        description={copy?.description ?? ""}
        confirmLabel={copy?.label ?? "확인"}
        cancelLabel="취소"
        danger
        onConfirm={() => void runConfirmed()}
        onCancel={() => setConfirm(null)}
      />

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
  busy: boolean;
  onInvited: (message: string) => void;
  onError: (message: string) => void;
  onRemoveManager: () => void;
  onDeactivate: () => void;
  onActivate: () => void;
  onDelete: () => void;
}

function TenantRow({
  tenant,
  busy,
  onInvited,
  onError,
  onRemoveManager,
  onDeactivate,
  onActivate,
  onDelete,
}: TenantRowProps) {
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>(undefined);
  const [inviting, setInviting] = useState(false);
  const inactive = tenant.status !== "active";

  async function invite() {
    const trimmed = email.trim();
    if (!EMAIL_RE.test(trimmed)) {
      setEmailError("이메일 형식이 올바르지 않습니다.");
      return;
    }
    setEmailError(undefined);
    setInviting(true);
    try {
      await inviteManager(tenant.id, trimmed);
      setEmail("");
      onInvited(`${trimmed} 앞으로 소장 초대 메일을 발송했습니다.`);
    } catch (err) {
      onError(err instanceof ApiError || err instanceof Error ? err.message : "초대에 실패했습니다.");
    } finally {
      setInviting(false);
    }
  }

  return (
    <li className="tn-row" data-inactive={inactive || undefined}>
      <div className="tn-row__head">
        <span className="tn-row__name">{tenant.name}</span>
        <span className={inactive ? "tn-status tn-status--inactive" : "tn-status"}>
          {inactive ? "비활성" : "운영 중"}
        </span>
        <span className="tn-row__date">생성 {tenant.createdAt.slice(0, 10)}</span>
        <span className="tn-row__actions">
          {inactive ? (
            <Button variant="secondary" size="sm" disabled={busy} onClick={onActivate}>
              재활성화
            </Button>
          ) : (
            <Button variant="secondary" size="sm" disabled={busy} onClick={onDeactivate}>
              비활성화
            </Button>
          )}
          <Button variant="danger" size="sm" disabled={busy} onClick={onDelete}>
            삭제
          </Button>
        </span>
      </div>

      {tenant.manager ? (
        <div className="tn-manager">
          <span className="tn-manager__label">소장</span>
          <span className="tn-manager__email">{tenant.manager.email ?? "이메일 미기록"}</span>
          <span
            className={`tn-manager__status tn-manager__status--${tenant.manager.status}`}
          >
            {MANAGER_STATUS_LABEL[tenant.manager.status] ?? tenant.manager.status}
          </span>
          <Button variant="danger" size="sm" disabled={busy} onClick={onRemoveManager}>
            소장 제거
          </Button>
        </div>
      ) : (
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
          <Button type="submit" variant="secondary" size="sm" disabled={inviting || inactive}>
            {inviting ? "발송 중…" : "소장 초대"}
          </Button>
        </form>
      )}
    </li>
  );
}
