"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { API_BASE_URL, listApprovals, listReviewQueue } from "@/lib/api";
import "./admin-shell.css";

/** 로그아웃 — 세션 revoke(멱등) 후 로그인 화면으로. 실패해도 로그인으로 이동. */
async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/auth/logout`, { method: "POST", credentials: "include" });
  } finally {
    window.location.href = "/login";
  }
}

interface NavItem {
  href: string;
  icon: string;
  label: string;
}

const NAV: readonly NavItem[] = [
  { href: "/dashboard", icon: "📊", label: "대시보드" },
  { href: "/approvals", icon: "👥", label: "가입 승인" },
  { href: "/review-queue", icon: "✅", label: "AI 검수 큐" },
  { href: "/notices/new", icon: "📢", label: "공지 초안" },
  { href: "/inquiries", icon: "🛠", label: "민원 관리" },
  { href: "/documents", icon: "📁", label: "문서 관리" },
  { href: "/fees", icon: "💰", label: "관리비 관리" },
  { href: "/facilities", icon: "🏢", label: "시설 관리" },
];

/** 처리 대기 카운트(href → 배지). 실패 항목은 배지를 숨긴다(정보 노출 최소·오해 방지). */
function usePendingBadges(enabled: boolean): Record<string, number> {
  const [badges, setBadges] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    // 마운트 시 1회 조회(폴링 없음). 각 카운트는 독립 — 하나가 실패해도 나머지는 표시.
    void listApprovals()
      .then((items) => alive && setBadges((prev) => ({ ...prev, "/approvals": items.length })))
      .catch(() => undefined);
    void listReviewQueue()
      .then((list) => alive && setBadges((prev) => ({ ...prev, "/review-queue": list.total })))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [enabled]);

  return badges;
}

/** 관리자 콘솔 셸 — 좌측 사이드바 내비 + 사용자 + 메인 영역. */
export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isLogin = pathname === "/login";
  const badges = usePendingBadges(!isLogin);

  // 로그인 화면은 셸(사이드바) 없이 전체 화면으로 — 미인증 진입점.
  if (isLogin) {
    return <>{children}</>;
  }

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-sidebar__brand">
          <span className="admin-sidebar__logo" aria-hidden="true">
            L
          </span>
          <span className="admin-sidebar__brand-text">
            <span className="admin-sidebar__name">LIVIQ</span>
            <span className="admin-sidebar__role">관리자 콘솔</span>
          </span>
        </div>

        <nav className="admin-nav" aria-label="관리 메뉴">
          {NAV.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const badge = badges[item.href];
            return (
              <Link
                key={item.href}
                href={item.href}
                className="admin-nav__item"
                data-active={active || undefined}
                aria-current={active ? "page" : undefined}
              >
                <span className="admin-nav__icon" aria-hidden="true">
                  {item.icon}
                </span>
                <span className="admin-nav__label">{item.label}</span>
                {badge ? <span className="admin-nav__badge">{badge}</span> : null}
              </Link>
            );
          })}
        </nav>

        <div className="admin-sidebar__user">
          <span className="admin-sidebar__avatar" aria-hidden="true">
            김
          </span>
          <span className="admin-sidebar__user-text">
            <span className="admin-sidebar__user-name">김*수 소장</span>
            <span className="admin-sidebar__user-org">관리사무소</span>
          </span>
          <button
            type="button"
            className="admin-sidebar__logout"
            onClick={() => void logout()}
          >
            로그아웃
          </button>
        </div>
      </aside>

      <div className="admin-main">{children}</div>
    </div>
  );
}
