// 역할별 내비·첫 진입 라우팅 (H7-2, ADR-0014).
// 숨김은 보조일 뿐 — 실제 인가는 서버 403(콘텐츠 라우터의 require_roles)이 본체.
// SYS_ADMIN은 단지 관리만, STAFF(소장 아님)는 민원·공지·문서만, MANAGER는 전체+직원 관리.

export interface NavItem {
  href: string;
  icon: string;
  label: string;
}

// 내비 항목 카탈로그 — 라우트별 단일 정의(중복 방지).
const DASHBOARD: NavItem = { href: "/dashboard", icon: "📊", label: "대시보드" };
const RESIDENTS: NavItem = { href: "/residents", icon: "🙋", label: "주민 관리" };
const NOTICES: NavItem = { href: "/notices", icon: "📢", label: "공지사항" };
const INQUIRIES: NavItem = { href: "/inquiries", icon: "🛠", label: "민원 관리" };
const DOCUMENTS: NavItem = { href: "/documents", icon: "📁", label: "문서 관리" };
const FEES: NavItem = { href: "/fees", icon: "💰", label: "관리비 관리" };
const FACILITIES: NavItem = { href: "/facilities", icon: "🏢", label: "시설 관리" };
const STAFF_MGMT: NavItem = { href: "/staff", icon: "🪪", label: "직원 관리" };
const SETTINGS_CODES: NavItem = { href: "/settings/codes", icon: "⚙️", label: "코드 관리" };
const SETTINGS_HOUSEHOLDS: NavItem = { href: "/settings/households", icon: "🏠", label: "동/호수 관리" };
const TENANTS: NavItem = { href: "/system/tenants", icon: "🏘", label: "단지 관리" };

// STAFF는 민원·공지(초안)·문서만(대시보드·관리비·시설·승인 숨김).
const STAFF_NAV: readonly NavItem[] = [INQUIRIES, NOTICES, DOCUMENTS];
// SYS_ADMIN은 단지 관리 하나만 — 어떤 단지 콘텐츠에도 접근하지 않는다.
const SYS_ADMIN_NAV: readonly NavItem[] = [TENANTS];
// MANAGER(기본): 전체 + 직원 관리(H7-5에서 설정 하위 → 최상위 승격).
const MANAGER_NAV: readonly NavItem[] = [
  DASHBOARD,
  RESIDENTS,
  NOTICES,
  INQUIRIES,
  DOCUMENTS,
  FEES,
  FACILITIES,
  STAFF_MGMT,
  SETTINGS_CODES,
  SETTINGS_HOUSEHOLDS,
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

/** 역할 → 첫 진입 경로. SYS_ADMIN=단지 관리 · STAFF=민원 · 그 외=대시보드(H7-6). */
export function roleHome(roles: readonly string[]): string {
  if (isSysAdmin(roles)) return TENANTS.href;
  if (isStaffOnly(roles)) return INQUIRIES.href;
  return DASHBOARD.href;
}

/** 역할 → 사이드바 표시 라벨(H7-5 — 하드코딩 "관리자/관리사무소" 대체). */
export function roleLabel(roles: readonly string[]): string {
  if (isSysAdmin(roles)) return "시스템 관리자";
  if (roles.includes("MANAGER")) return "관리소장";
  if (roles.includes("STAFF")) return "직원";
  return "관리자";
}
