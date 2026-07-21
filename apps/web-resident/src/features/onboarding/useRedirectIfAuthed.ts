"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { API_BASE_URL, DEV_HEADERS } from "@/lib/dev-context";
import { authedRedirect } from "./logic";

/**
 * 인증 진입 화면(/login·/signup) 가드 — 이미 로그인한 사용자를 상태별 화면으로 보낸다
 * (active→/home · registered→/onboarding). /me 를 직접 호출한다(apiFetch 미사용):
 * 미로그인(401)이어도 로그인으로 튕기지 않고 화면에 머물러 가입·로그인 폼을 노출하기 위함이다.
 */
export function useRedirectIfAuthed(): void {
  const router = useRouter();

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/me`, {
          credentials: "include",
          headers: DEV_HEADERS,
        });
        if (!alive || !res.ok) return;
        const body = await res.json();
        const dest = authedRedirect(body.status);
        if (dest) router.replace(dest);
      } catch {
        // 네트워크 오류·미로그인은 무시 — 폼을 그대로 노출한다.
      }
    })();
    return () => {
      alive = false;
    };
  }, [router]);
}
