// api HTTP 클라이언트 공통 — 세션 쿠키 인증(credentials) + local dev 헤더 보조.
// assistant·inquiries·fees·notices 등 여러 클라이언트가 공유 — 상수·래퍼 중복 방지.

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// dev 헤더는 NEXT_PUBLIC_DEV_TENANT_ID가 설정된 local 편의 환경에서만 부착한다.
// 기본(미설정)은 세션 쿠키 인증만 사용 — api는 local에서만 dev 헤더를 허용(deps.get_context).
const DEV_TENANT_ID = process.env.NEXT_PUBLIC_DEV_TENANT_ID;
const DEV_USER_ID = process.env.NEXT_PUBLIC_DEV_USER_ID;

export const DEV_HEADERS: Record<string, string> =
  DEV_TENANT_ID && DEV_USER_ID
    ? { "X-Dev-Tenant-Id": DEV_TENANT_ID, "X-Dev-User-Id": DEV_USER_ID }
    : {};

/**
 * 세션 쿠키를 실어 api를 호출하는 fetch 래퍼.
 * - credentials:"include" — 교차 출처(3000→8000) 세션 쿠키 전송(ADR-0011).
 * - DEV_HEADERS 병합(local 보조) + 호출자 헤더가 우선.
 * - 401(미인증·만료)이면 로그인 화면으로 유도(이미 /login이면 루프 방지).
 */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(input, {
    ...init,
    credentials: "include",
    headers: { ...DEV_HEADERS, ...(init.headers as Record<string, string> | undefined) },
  });
  if (
    response.status === 401 &&
    typeof window !== "undefined" &&
    window.location.pathname !== "/login"
  ) {
    window.location.href = "/login";
  }
  return response;
}
