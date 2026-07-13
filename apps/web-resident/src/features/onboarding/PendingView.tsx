"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@liviq/ui";
import { maskKoreanName } from "./logic";
import "./onboarding.css";

/** 계정 상태 3종. 목업이라 서버 대신 데모 토글로 전환한다. */
type AccountState = "pending" | "rejected" | "inactive";

const STATE_LABEL: Record<AccountState, string> = {
  pending: "대기",
  rejected: "거절",
  inactive: "비활성",
};

const APPLICATION = {
  name: "홍길동",
  dong: "101",
  ho: "1002",
} as const;

export function PendingView() {
  const router = useRouter();
  const [state, setState] = useState<AccountState>("pending");

  return (
    <main id="main" className="auth-shell">
      <div className="auth-inner">
        <div className="auth-brand auth-brand--sm">
          <span className="auth-brand__logo" aria-hidden="true">
            L
          </span>
          <span className="auth-brand__wordmark">LIVIQ</span>
        </div>

        <div className="auth-demo" role="group" aria-label="데모 계정 상태 전환">
          <span className="auth-demo__label">데모 상태</span>
          <div className="auth-seg">
            {(Object.keys(STATE_LABEL) as AccountState[]).map((key) => (
              <button
                key={key}
                type="button"
                className="auth-seg__btn"
                data-active={state === key || undefined}
                aria-pressed={state === key}
                onClick={() => setState(key)}
              >
                {STATE_LABEL[key]}
              </button>
            ))}
          </div>
        </div>

        <section className="auth-status" aria-live="polite">
          {state === "pending" ? <PendingCard /> : null}
          {state === "rejected" ? <RejectedCard onReapply={() => router.push("/signup")} /> : null}
          {state === "inactive" ? <InactiveCard /> : null}
        </section>
      </div>
    </main>
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

      <span className="auth-verify auth-verify--ok">
        <span aria-hidden="true">✓</span> 입주민 명부와 일치 확인됨
      </span>

      <dl className="auth-summary">
        <div className="auth-summary__row">
          <dt>이름</dt>
          <dd>{maskKoreanName(APPLICATION.name)}</dd>
        </div>
        <div className="auth-summary__row">
          <dt>동·호</dt>
          <dd>
            {APPLICATION.dong}동 {APPLICATION.ho}호
          </dd>
        </div>
      </dl>
    </div>
  );
}

function RejectedCard({ onReapply }: { onReapply: () => void }) {
  return (
    <div className="auth-state-card">
      <div className="auth-state__icon auth-state__icon--danger" aria-hidden="true">
        ⚠
      </div>
      <h1 className="auth-state__title">신청이 반려되었어요</h1>
      <p className="auth-state__reason">
        <span aria-hidden="true">사유 · </span>동·호수 정보가 명부와 달라요.
      </p>
      <p className="auth-state__desc">
        정보를 확인해 다시 신청해 주세요. 명부가 최신이 아닐 수 있으니 관리사무소에 문의하셔도 됩니다.
      </p>
      <Button type="button" variant="primary" className="auth-submit" onClick={onReapply}>
        정보 수정 후 재신청
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
