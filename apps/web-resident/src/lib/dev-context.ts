// local dev 전용 컨텍스트(정식 세션 인증 도입 전). 실제 시드된 tenant/user 와 일치해야 함.
// dev 헤더 경로는 roles=(RESIDENT,MANAGER,STAFF) 부여 — 민원 접수(RESIDENT) 통과.
// assistant·inquiries 등 여러 클라이언트가 공유 — 상수 중복 방지.

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const DEV_TENANT_ID =
  process.env.NEXT_PUBLIC_DEV_TENANT_ID ?? "11111111-1111-1111-1111-111111111111";
const DEV_USER_ID =
  process.env.NEXT_PUBLIC_DEV_USER_ID ?? "22222222-2222-2222-2222-222222222222";

export const DEV_HEADERS: Record<string, string> = {
  "X-Dev-Tenant-Id": DEV_TENANT_ID,
  "X-Dev-User-Id": DEV_USER_ID,
};
