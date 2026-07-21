"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@liviq/ui";
import { ApiError, getMe, listNotifications } from "@/lib/api";
import { accountView, rejectionReasonFrom, type AccountView } from "./logic";
import "./onboarding.css";

/** 계정 상태 화면 — /me 실상태로 분기(대기·반려·활성·비활성). 반려 사유는 인앱 알림에서 조회. */
export function PendingView() {
  const router = useRouter();
  const [view, setView] = useState<AccountView | "loading" | "error">("loading");
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const me = await getMe();
        if (!alive) return;
        const next = accountView(me);
        // 미제출(registered)이면 입주민 정보 입력(온보딩)으로 되돌린다.
        if (next === "onboarding") {
          router.replace("/onboarding");
          return;
        }
        // 반려 사유는 승인 알림함에 실려 온다 — 반려 상태에서만 추가 조회.
        if (next === "rejected") {
          const notifications = await listNotifications();
          if (!alive) return;
          setReason(rejectionReasonFrom(notifications));
        }
        setView(next);
      } catch (err) {
        // 401 은 apiFetch 가 /login 으로 유도 — 여기 도달하는 건 그 외 오류.
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) return;
        setView("error");
      }
    })();
    return () => {
      alive = false;
    };
  }, [router]);

  return (
    <main id="main" className="auth-shell">
      <div className="auth-inner">
        <div className="auth-brand auth-brand--sm">
          <span className="auth-brand__logo" aria-hidden="true">
            L
          </span>
          <span className="auth-brand__wordmark">LIVIQ</span>
        </div>

        <section className="auth-status" aria-live="polite">
          {view === "loading" ? <StatusMessage title="계정 상태를 확인하고 있어요…" /> : null}
          {view === "error" ? (
            <StatusMessage title="상태를 불러오지 못했어요" desc="잠시 후 다시 시도해 주세요." />
          ) : null}
          {view === "pending" ? <PendingCard /> : null}
          {view === "rejected" ? (
            <RejectedCard reason={reason} onReapply={() => router.push("/onboarding")} />
          ) : null}
          {view === "active" ? <ActiveCard onEnter={() => router.push("/home")} /> : null}
          {view === "inactive" ? <InactiveCard /> : null}
          {view === "unknown" ? (
            <StatusMessage title="가입 처리 중입니다" desc="상태가 확정되면 알림으로 안내드립니다." />
          ) : null}
        </section>
      </div>
    </main>
  );
}

function StatusMessage({ title, desc }: { title: string; desc?: string }) {
  return (
    <div className="auth-state-card">
      <h1 className="auth-state__title">{title}</h1>
      {desc ? <p className="auth-state__desc">{desc}</p> : null}
    </div>
  );
}

function PendingCard() {
  return (
    <div className="auth-state-card">
      <div className="auth-state__icon" aria-hidden="true">
        ⏳
      </div>
      <h1 className="auth-state__title">관리소장 승인을 기다리고 있어요</h1>
      <p className="auth-state__desc">
        신청이 접수되었습니다. 관리사무소에서 입주민 명부와 대조해 승인하면 알림으로 안내드립니다.
      </p>
    </div>
  );
}

function RejectedCard({ reason, onReapply }: { reason: string | null; onReapply: () => void }) {
  return (
    <div className="auth-state-card">
      <div className="auth-state__icon auth-state__icon--danger" aria-hidden="true">
        ⚠
      </div>
      <h1 className="auth-state__title">신청이 반려되었어요</h1>
      {reason ? (
        <p className="auth-state__reason">
          <span aria-hidden="true">사유 · </span>
          {reason}
        </p>
      ) : null}
      <p className="auth-state__desc">
        정보를 확인해 다시 신청해 주세요. 명부가 최신이 아닐 수 있으니 관리사무소에 문의하셔도 됩니다.
      </p>
      <Button type="button" variant="primary" className="auth-submit" onClick={onReapply}>
        정보 수정 후 재신청
      </Button>
    </div>
  );
}

function ActiveCard({ onEnter }: { onEnter: () => void }) {
  return (
    <div className="auth-state-card">
      <div className="auth-state__icon" aria-hidden="true">
        🎉
      </div>
      <h1 className="auth-state__title">가입이 승인되었어요</h1>
      <p className="auth-state__desc">이제 우리 단지 AI 생활 비서를 이용할 수 있습니다.</p>
      <Button type="button" variant="primary" className="auth-submit" onClick={onEnter}>
        홈으로 가기
      </Button>
    </div>
  );
}

function InactiveCard() {
  return (
    <div className="auth-state-card">
      <div className="auth-state__icon" aria-hidden="true">
        🚫
      </div>
      <h1 className="auth-state__title">이용이 중지된 계정입니다</h1>
      <p className="auth-state__desc">
        전출 등으로 비활성화된 계정입니다. 다시 이용하려면 관리사무소에 문의해 주세요.
      </p>
    </div>
  );
}
