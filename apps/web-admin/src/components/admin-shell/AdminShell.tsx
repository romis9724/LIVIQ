"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { API_BASE_URL, getMe, listApprovals, type Me } from "@/lib/api";
import { isSysAdmin, navForRoles, roleHome, roleLabel } from "@/lib/roles";
import "./admin-shell.css";

// 셸 없이 전체 화면으로 렌더하는 라우트 — 미인증/강제 전환 진입점.
const CHROMELESS = new Set(["/login", "/invite", "/password-change"]);

/** 로그아웃 — 세션 revoke(멱등) 후 로그인 화면으로. 실패해도 로그인으로 이동. */
async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/auth/logout`, { method: "POST", credentials: "include" });
  } finally {
    window.location.href = "/login";
  }
}

/** /me 1회 조회. undefined=로딩 · null=실패(권한 미상, 폴백 렌더). */
function useMe(enabled: boolean): Me | null | undefined {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    void getMe()
      .then((value) => alive && setMe(value))
      .catch(() => alive && setMe(null)); // 401은 apiFetch가 로그인으로 유도
    return () => {
      alive = false;
    };
  }, [enabled]);
  return me;
}

/** 처리 대기 카운트(href → 배지). MANAGER만 조회 — STAFF/SYS_ADMIN은 403이라 생략. */
function usePendingBadges(enabled: boolean): Record<string, number> {
  const [badges, setBadges] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    // 마운트 시 1회 조회(폴링 없음). 각 카운트는 독립 — 하나가 실패해도 나머지는 표시.
    void listApprovals()
      .then((items) => alive && setBadges((prev) => ({ ...prev, "/residents": items.length })))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [enabled]);

  return badges;
}

/** 로딩/리다이렉트 중 표시 — 잘못된 내비가 번쩍이지 않도록 셸을 가린다. */
function ShellLoading() {
  return (
    <div className="admin-loading" role="status" aria-live="polite">
      불러오는 중…
    </div>
  );
}

/** 관리자 콘솔 셸 — 좌측 사이드바 내비 + 사용자 + 메인 영역. */
export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isChromeless = CHROMELESS.has(pathname);
  const me = useMe(!isChromeless);
  const roles = me?.roles ?? [];
  const isManager = me !== null && me !== undefined && roles.includes("MANAGER");
  const badges = usePendingBadges(!isChromeless && isManager);

  // 역할·상태 기반 라우팅(숨김은 보조 — 서버 403이 본체).
  useEffect(() => {
    if (isChromeless || me === undefined || me === null) return;
    if (me.mustChangePassword) {
      router.replace("/password-change");
      return;
    }
    if (pathname === "/") {
      router.replace(roleHome(me.roles));
      return;
    }
    // SYS_ADMIN은 단지 관리 밖으로 나가면 되돌린다(콘텐츠 비열람 원칙, 규칙 4).
    if (isSysAdmin(me.roles) && !pathname.startsWith("/system")) {
      router.replace("/system/tenants");
    }
  }, [isChromeless, me, pathname, router]);

  // 로그인·초대·비밀번호 변경은 셸(사이드바) 없이 전체 화면으로.
  if (isChromeless) {
    return <>{children}</>;
  }

  // 로딩 중이거나 리다이렉트가 예정된 경로는 셸 대신 로딩을 보여 오노출을 막는다.
  const redirecting =
    me !== null &&
    me !== undefined &&
    (me.mustChangePassword ||
      pathname === "/" ||
      (isSysAdmin(me.roles) && !pathname.startsWith("/system")));
  if (me === undefined || redirecting) {
    return <ShellLoading />;
  }

  const nav = navForRoles(roles);

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
          {nav.map((item) => {
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
            {(me?.email ?? "?").charAt(0).toUpperCase()}
          </span>
          <span className="admin-sidebar__user-text">
            <span className="admin-sidebar__user-name">{roleLabel(roles)}</span>
            <span className="admin-sidebar__user-org" title={me?.email ?? undefined}>
              {me?.email ?? "로그인 계정"}
            </span>
          </span>
          <button type="button" className="admin-sidebar__logout" onClick={() => void logout()}>
            로그아웃
          </button>
        </div>
      </aside>

      <div className="admin-main">{children}</div>
    </div>
  );
}
