"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Skeleton } from "@liviq/ui";
import { API_BASE_URL } from "@/lib/dev-context";
import { ApiError, getMe, type Me } from "@/lib/api";
import { formatWon, getFees, type FeeData } from "../fees/api";
import { currentPeriod, unitWithTenant } from "../home/logic";
import { NotificationInbox } from "./NotificationInbox";
import { accountStatusLabel, feePeriodLabel, roleLabel } from "./logic";
import "./me.css";

/** 로그아웃 — 세션 revoke(멱등) 후 로그인 화면으로. 실패해도 로그인으로 이동. */
async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/auth/logout`, { method: "POST", credentials: "include" });
  } finally {
    window.location.href = "/login";
  }
}

/** 섹션별 독립 로딩 — 관리비 실패가 프로필을 막지 않는다. */
type Loadable<T> = { status: "loading" } | { status: "error" } | { status: "ready"; data: T };

export function MeView() {
  const period = currentPeriod();
  const [me, setMe] = useState<Me | null>(null);
  const [meError, setMeError] = useState(false);
  const [fee, setFee] = useState<Loadable<FeeData>>({ status: "loading" });

  useEffect(() => {
    let alive = true;
    getMe()
      .then((data) => alive && setMe(data))
      .catch((err) => {
        // 401 은 apiFetch 가 /login 으로 유도. 그 외 오류만 표시.
        if (!alive || (err instanceof ApiError && err.status === 401)) return;
        setMeError(true);
      });
    getFees(period)
      .then((data) => alive && setFee({ status: "ready", data }))
      .catch(() => alive && setFee({ status: "error" }));
    return () => {
      alive = false;
    };
  }, [period]);

  return (
    <main id="main" className="me">
      <div className="me-profile">
        <span className="me-profile__avatar" aria-hidden="true">
          👤
        </span>
        <div className="me-profile__info">
          {me ? (
            <>
              <div className="me-profile__name">{me.displayName ?? roleLabel(me.roles)}</div>
              <div className="me-profile__sub">
                {unitWithTenant(me.tenantName, me.unitLabel) ?? accountStatusLabel(me.status)}
              </div>
            </>
          ) : meError ? (
            <div className="me-profile__sub">계정 정보를 불러오지 못했어요.</div>
          ) : (
            <Skeleton height="2.4rem" width="12rem" />
          )}
        </div>
      </div>

      <NotificationInbox />

      <section className="me-section">
        <h2 className="me-section__title">관리비</h2>
        <Link href="/fees" className="me-fee">
          <span className="me-fee__body">
            <span className="me-fee__period">{feePeriodLabel(period)}</span>
            {fee.status === "loading" ? (
              <Skeleton height="1.6rem" width="8rem" />
            ) : fee.status === "error" || fee.data.total === null ? (
              <span className="me-fee__empty">이번 달 관리비가 아직 없어요</span>
            ) : (
              <span className="me-fee__amount">{formatWon(fee.data.total)}</span>
            )}
          </span>
          <span className="me-fee__more" aria-hidden="true">
            자세히 →
          </span>
        </Link>
      </section>

      <section className="me-section">
        <h2 className="me-section__title">개인정보</h2>
        <div className="me-privacy">
          <div className="me-privacy__intro">
            <span aria-hidden="true" className="me-privacy__lock">
              🔒
            </span>
            <p>
              AI 응대·담당자 전달 시 타인의 개인정보는 자동 마스킹됩니다. 예: 홍*동 ·
              010-****-1234
            </p>
          </div>
          {/* 동의 변경 API 는 백로그 — 가입 시 받은 동의를 표시만 한다. */}
          <div className="me-consent">
            <div className="me-consent__row">
              <span>AI 응대 품질 개선을 위한 대화 활용 동의</span>
              <span className="me-consent__state">가입 시 동의 완료</span>
            </div>
            <div className="me-consent__row">
              <span>단지 공지·관리비 알림 수신 동의</span>
              <span className="me-consent__state">가입 시 동의 완료</span>
            </div>
          </div>
          <a href="#" className="me-privacy__link">
            개인정보 처리방침 보기 →
          </a>
        </div>
        <button type="button" className="me-logout" onClick={() => void logout()}>
          로그아웃
        </button>
      </section>
    </main>
  );
}
