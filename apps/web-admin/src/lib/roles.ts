// 역할별 내비·첫 진입 라우팅 (H7-2, ADR-0014).
// 숨김은 보조일 뿐 — 실제 인가는 서버 403(콘텐츠 라우터의 require_roles)이 본체.
// SYS_ADMIN은 단지 관리만, STAFF(소장 아님)는 민원·공지·문서만, MANAGER는 전체+설정.

export interface NavItem {
  href: string;
  icon: string;
  label: string;
}

// 내비 항목 카탈로그 — 라우트별 단일 정의(중복 방지).
const DASHBOARD: NavItem = { href: "/dashboard", icon: "📊", label: "대시보드" };
const APPROVALS: NavItem = { href: "/approvals", icon: "👥", label: "가입 승인" };
const REVIEW: NavItem = { href: "/review-queue", icon: "✅", label: "AI 검수 큐" };
const NOTICES: NavItem = { href: "/notices/new", icon: "📢", label: "공지 초안" };
const INQUIRIES: NavItem = { href: "/inquiries", icon: "🛠", label: "민원 관리" };
const DOCUMENTS: NavItem = { href: "/documents", icon: "📁", label: "문서 관리" };
const FEES: NavItem = { href: "/fees", icon: "💰", label: "관리비 관리" };
const FACILITIES: NavItem = { href: "/facilities", icon: "🏢", label: "시설 관리" };
const SETTINGS: NavItem = { href: "/settings", icon: "⚙️", label: "설정" };
const TENANTS: NavItem = { href: "/system/tenants", icon: "🏘", label: "단지 관리" };

// STAFF는 민원·공지(초안)·문서만(대시보드·관리비·시설·검수·승인 숨김).
const STAFF_NAV: readonly NavItem[] = [INQUIRIES, NOTICES, DOCUMENTS];
// SYS_ADMIN은 단지 관리 하나만 — 어떤 단지 콘텐츠에도 접근하지 않는다.
const SYS_ADMIN_NAV: readonly NavItem[] = [TENANTS];
// MANAGER(기본): 전체 + 설정(직원 관리).
const MANAGER_NAV: readonly NavItem[] = [
  DASHBOARD,
  APPROVALS,
  REVIEW,
  NOTICES,
  INQUIRIES,
  DOCUMENTS,
  FEES,
  FACILITIES,
  SETTINGS,
];

export function isSysAdmin(roles: readonly string[]): boolean {
  return roles.includes("SYS_ADMIN");
}

function isStaffOnly(roles: readonly string[]): boolean {
  return roles.includes("STAFF") && !roles.includes("MANAGER");
}

/** 역할 → 노출 내비. 미상(에러 등)이면 MANAGER 전체로 폴백 — 서버 403이 최종 방어. */
export function navForRoles(roles: readonly string[]): readonly NavItem[] {
  if (isSysAdmin(roles)) return SYS_ADMIN_NAV;
  if (isStaffOnly(roles)) return STAFF_NAV;
  return MANAGER_NAV;
}

/** 역할 → 첫 진입 경로. SYS_ADMIN=단지 관리 · STAFF=민원 · 그 외=검수 큐. */
export function roleHome(roles: readonly string[]): string {
  if (isSysAdmin(roles)) return TENANTS.href;
  if (isStaffOnly(roles)) return INQUIRIES.href;
  return REVIEW.href;
}
