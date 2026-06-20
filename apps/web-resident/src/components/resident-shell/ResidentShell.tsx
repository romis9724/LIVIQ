"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import "./resident-shell.css";

interface Tab {
  href: string;
  icon: string;
  label: string;
}

const TABS: readonly Tab[] = [
  { href: "/home", icon: "🏠", label: "홈" },
  { href: "/assistant", icon: "💬", label: "AI 비서" },
  { href: "/notices", icon: "📢", label: "공지" },
  { href: "/inquiries", icon: "🛠", label: "민원" },
  { href: "/me", icon: "👤", label: "나" },
];

/** 입주민 앱 셸 — 모바일 우선 컨테이너 + 하단 탭 내비게이션. */
export function ResidentShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="resident-shell">
      <div className="resident-shell__content">{children}</div>
      <nav className="resident-tabbar" aria-label="주요 메뉴">
        {TABS.map((tab) => {
          const active = pathname === tab.href || pathname.startsWith(`${tab.href}/`);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className="resident-tabbar__item"
              data-active={active || undefined}
              aria-current={active ? "page" : undefined}
            >
              <span className="resident-tabbar__icon" aria-hidden="true">
                {tab.icon}
              </span>
              <span className="resident-tabbar__label">{tab.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
