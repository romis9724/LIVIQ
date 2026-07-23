"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Dialog, EmptyState, FormField, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  deactivateStaff,
  deleteStaff,
  getMe,
  inviteStaff,
  listStaff,
  type StaffMember,
} from "@/lib/api";
import "./staff.css";

const TOAST_DURATION_MS = 3200;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const ROLE_LABEL: Record<string, string> = { MANAGER: "소장", STAFF: "직원" };
const STATUS_LABEL: Record<string, string> = {
  invited: "초대됨",
  active: "활성",
  inactive: "비활성",
};

type ToastState = { message: string; tone: ToastTone };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

function roleText(roles: string[]): string {
  return roles.map((r) => ROLE_LABEL[r] ?? r).join(" · ");
}

/** STAFF 전용(소장 아님)·비활성 아님일 때만 비활성화 가능. 소장·자기 자신은 서버도 400. */
function canDeactivate(member: StaffMember): boolean {
  return (
    member.roles.includes("STAFF") &&
    !member.roles.includes("MANAGER") &&
    member.status !== "inactive"
  );
}

export function StaffAdmin() {
  const [staff, setStaff] = useState<StaffMember[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>(undefined);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | undefined>(undefined);
  const [inviting, setInviting] = useState(false);
  const [deactivateTarget, setDeactivateTarget] = useState<StaffMember | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<StaffMember | null>(null);
  const [meId, setMeId] = useState<string | null>(null);
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
      setStaff(await listStaff());
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
      setStaff([]);
    }
  }, []);

  useEffect(() => {
    void load();
    // 자기 자신 행에는 삭제 버튼을 숨긴다(서버도 400) — 실패해도 목록은 동작.
    void getMe()
      .then((me) => setMeId(me.userId))
      .catch(() => setMeId(null));
  }, [load]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  async function submitInvite() {
    const trimmedEmail = email.trim();
    const trimmedName = name.trim();
    const emailOk = EMAIL_RE.test(trimmedEmail);
    const nameOk = trimmedName.length > 0;
    setEmailError(emailOk ? undefined : "이메일 형식이 올바르지 않습니다.");
    setNameError(nameOk ? undefined : "이름을 입력해 주세요.");
    if (!emailOk || !nameOk) return;
    setInviting(true);
    try {
      await inviteStaff({ email: trimmedEmail, name: trimmedName });
      setEmail("");
      setName("");
      await load();
      showToast(`${trimmedName}(${trimmedEmail}) 앞으로 직원 초대 메일을 발송했습니다.`);
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setInviting(false);
    }
  }

  async function confirmDeactivate() {
    if (!deactivateTarget) return;
    const userId = deactivateTarget.userId;
    setBusyId(userId);
    try {
      await deactivateStaff(userId);
      setDeactivateTarget(null);
      await load();
      showToast("직원을 비활성화했습니다. 진행 중이던 세션은 즉시 종료됩니다.", "neutral");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    const userId = deleteTarget.userId;
    setBusyId(userId);
    try {
      await deleteStaff(userId);
      setDeleteTarget(null);
      await load();
      showToast("계정을 삭제했습니다. 같은 이메일로 다시 초대할 수 있습니다.", "neutral");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          직원 관리
        </h1>
        <p className="admin-page__lede">
          단지 직원을 초대하고 관리합니다. 초대 메일의 링크로 직원이 비밀번호를 설정하면 계정이
          활성화됩니다.
        </p>
      </header>

      <main className="admin-page__main">
        <section className="surface-card sf-invite" aria-labelledby="sf-invite-h">
          <h2 id="sf-invite-h" className="sf-section__title">
            직원 초대
          </h2>
          <form
            className="sf-invite__form"
            onSubmit={(e) => {
              e.preventDefault();
              void submitInvite();
            }}
            noValidate
          >
            <FormField
              label="직원 이름"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              error={nameError}
              autoComplete="off"
              placeholder="홍길동"
              wrapperClassName="sf-invite__field"
            />
            <FormField
              label="직원 이메일"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={emailError}
              autoComplete="off"
              inputMode="email"
              placeholder="staff@example.com"
              wrapperClassName="sf-invite__field"
            />
            <Button type="submit" variant="primary" disabled={inviting}>
              {inviting ? "발송 중…" : "직원 초대"}
            </Button>
          </form>
        </section>

        <section className="sf-list" aria-labelledby="sf-list-h">
          <h2 id="sf-list-h" className="sf-section__title">
            직원 목록
          </h2>

          {loadError ? (
            <EmptyState icon="⚠" title="목록을 불러오지 못했습니다" description={loadError} />
          ) : staff === null ? (
            <div className="sf-rows">
              <Skeleton height="64px" />
              <Skeleton height="64px" />
            </div>
          ) : staff.length === 0 ? (
            <EmptyState
              icon="👥"
              title="등록된 직원이 없습니다"
              description="위에서 직원을 초대해 보세요."
            />
          ) : (
            <ul className="sf-rows">
              {staff.map((member) => (
                <li key={member.userId} className="sf-row">
                  <div className="sf-row__main">
                    <span className="sf-row__name">{member.name ?? "이름 미기록"}</span>
                    <span className="sf-row__email">{member.email ?? "이메일 미기록"}</span>
                    <span className="sf-row__roles">{roleText(member.roles)}</span>
                    <span className={`sf-status sf-status--${member.status}`}>
                      {STATUS_LABEL[member.status] ?? member.status}
                    </span>
                  </div>
                  <span className="sf-row__date">초대 {member.invitedAt.slice(0, 10)}</span>
                  {canDeactivate(member) ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busyId === member.userId}
                      onClick={() => setDeactivateTarget(member)}
                    >
                      비활성화
                    </Button>
                  ) : null}
                  {member.userId !== meId ? (
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={busyId === member.userId}
                      onClick={() => setDeleteTarget(member)}
                    >
                      삭제
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>

      <Dialog
        open={deactivateTarget !== null}
        title="직원을 비활성화할까요?"
        description="비활성화하면 이 직원은 더 이상 로그인할 수 없고, 진행 중이던 세션도 즉시 종료됩니다."
        confirmLabel="비활성화"
        cancelLabel="취소"
        danger
        onConfirm={() => void confirmDeactivate()}
        onCancel={() => setDeactivateTarget(null)}
      />

      <Dialog
        open={deleteTarget !== null}
        title="계정을 삭제할까요?"
        description={`${deleteTarget?.email ?? "이 계정"}을(를) 삭제합니다. 개인정보가 비식별 처리되고 복구할 수 없습니다. 같은 이메일로 다시 초대하는 것은 가능합니다.`}
        confirmLabel="삭제"
        cancelLabel="취소"
        danger
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteTarget(null)}
      />

      {toast ? (
        <div className="sf-toast">
          <Toast tone={toast.tone} message={toast.message} />
        </div>
      ) : null}
    </>
  );
}
