"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import "./admin-shell.css";

interface NavItem {
  href: string;
  icon: string;
  label: string;
  badge?: string;
}

const NAV: readonly NavItem[] = [
  { href: "/dashboard", icon: "📊", label: "대시보드" },
  { href: "/approvals", icon: "👥", label: "가입 승인", badge: "5" },
  { href: "/review-queue", icon: "✅", label: "AI 검수 큐", badge: "7" },
  { href: "/notices/new", icon: "📢", label: "공지 초안" },
  { href: "/inquiries", icon: "🛠", label: "민원 관리", badge: "3" },
  { href: "/documents", icon: "📁", label: "문서 관리" },
  { href: "/fees", icon: "💰", label: "관리비 관리" },
  { href: "/facilities", icon: "🏢", label: "시설 관리" },
];

/** 관리자 콘솔 셸 — 좌측 사이드바 내비 + 사용자 + 메인 영역. */
export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

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
                {item.badge ? <span className="admin-nav__badge">{item.badge}</span> : null}
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
        </div>
      </aside>

      <div className="admin-main">{children}</div>
    </div>
  );
}
