"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Skeleton } from "@liviq/ui";
import { ApiError, getMe } from "@/lib/api";
import { rootDestination } from "@/features/onboarding/logic";
import "./page.css";

/**
 * 루트(/) 디스패처 — OAuth 콜백 복귀 지점(auth.py _HOME_PATH="/").
 * /me 계정 상태로 분기해 replace 한다: active→/home · onboarding→/onboarding ·
 * 그 외(pending·rejected·inactive)→/pending. 401(미로그인)은 apiFetch 가 /login 으로 유도.
 */
export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const me = await getMe();
        if (!alive) return;
        router.replace(rootDestination(me));
      } catch (err) {
        // 401 은 apiFetch 가 이미 /login 으로 보냄. 그 외 오류도 로그인으로 폴백.
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) return;
        router.replace("/login");
      }
    })();
    return () => {
      alive = false;
    };
  }, [router]);

  return (
    <main id="main" className="root-splash" aria-busy="true">
      <span className="root-splash__logo" aria-hidden="true">
        L
      </span>
      <span className="root-splash__label">불러오는 중…</span>
      <Skeleton height="3rem" radius="var(--radius-md)" />
      <Skeleton height="8rem" radius="var(--radius-md)" />
    </main>
  );
}
