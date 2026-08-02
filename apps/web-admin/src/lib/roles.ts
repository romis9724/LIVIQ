// 역할별 내비·첫 진입 라우팅 (H7-2, ADR-0014).
// 숨김은 보조일 뿐 — 실제 인가는 서버 403(콘텐츠 라우터의 require_roles)이 본체.
// SYS_ADMIN은 단지 관리·AI 설정만, STAFF(소장 아님)는 민원·공지·문서만, MANAGER는 전체+직원 관리.

export interface NavItem {
  href: string;
  icon: string;
  label: string;
}

/** 내비 섹션 그룹 — title 없으면 헤더 없이 단독 렌더. */
export interface NavGroup {
  title?: string;
  items: readonly NavItem[];
}

// 내비 항목 카탈로그 — 라우트별 단일 정의(중복 방지).
const ASSISTANT: NavItem = { href: "/assistant", icon: "💬", label: "AI 비서" };
const INQUIRY_STATUS: NavItem = { href: "/inquiry-status", icon: "📊", label: "민원현황" };
const RESIDENTS: NavItem = { href: "/residents", icon: "🙋", label: "주민 관리" };
const NOTICES: NavItem = { href: "/notices", icon: "📢", label: "공지사항" };
const INQUIRIES: NavItem = { href: "/inquiries", icon: "🛠", label: "민원 관리" };
const DOCUMENTS: NavItem = { href: "/documents", icon: "📁", label: "문서 관리" };
const FEES: NavItem = { href: "/fees", icon: "💰", label: "관리비 관리" };
const FACILITIES: NavItem = { href: "/facilities", icon: "🏢", label: "시설 관리" };
const TWIN: NavItem = { href: "/twin", icon: "🧊", label: "트윈 대시보드" };
const PARKING: NavItem = { href: "/parking", icon: "🅿️", label: "주차장 대시보드" };
const STAFF_MGMT: NavItem = { href: "/staff", icon: "🪪", label: "직원 관리" };
const SETTINGS_CODES: NavItem = { href: "/settings/codes", icon: "⚙️", label: "코드 관리" };
const SETTINGS_HOUSEHOLDS: NavItem = { href: "/settings/households", icon: "🏠", label: "동/호수 관리" };
const TENANTS: NavItem = { href: "/system/tenants", icon: "🏘", label: "단지 관리" };
const SYSTEM_AI: NavItem = { href: "/system/ai", icon: "🤖", label: "AI 설정" };

// STAFF는 민원·공지(초안)·문서만(AI 비서·민원현황·관리비·시설·승인 숨김) — 항목이 적어 그룹 없이 flat.
const STAFF_NAV: readonly NavGroup[] = [{ items: [INQUIRIES, NOTICES, DOCUMENTS] }];
// SYS_ADMIN은 단지 관리 + AI 설정(플랫폼 설정)만 — 어떤 단지 콘텐츠에도 접근하지 않는다(flat).
const SYS_ADMIN_NAV: readonly NavGroup[] = [{ items: [TENANTS, SYSTEM_AI] }];
// MANAGER(기본): 섹션 그룹화 — AI 비서·공지 단독, 입주민 관리·관리소 운영·설정 묶음.
// 첫 항목은 AI 비서(H20-2, ADR-0028) — 구 대시보드는 "관리소 운영 > 민원현황"으로 내려갔다.
// 트윈 대시보드는 geometry 등록(hasTwin) 시에만 AI 비서 바로 아래 같은 레벨로 노출(H9-4 — 확정 데이터 현황판).
// 주차장 대시보드는 트윈 바로 다음에 항상 노출(H9-5 — 확정 데이터 현황판, geometry 불필요).
function managerNav(hasTwin: boolean): readonly NavGroup[] {
  const top = hasTwin ? [ASSISTANT, TWIN, PARKING, NOTICES] : [ASSISTANT, PARKING, NOTICES];
  return [
    { items: top },
    { title: "입주민 관리", items: [RESIDENTS, FEES, INQUIRIES] },
    { title: "관리소 운영", items: [INQUIRY_STATUS, STAFF_MGMT, DOCUMENTS, FACILITIES] },
    { title: "설정", items: [SETTINGS_HOUSEHOLDS, SETTINGS_CODES] },
  ];
}

export function isSysAdmin(roles: readonly string[]): boolean {
  return roles.includes("SYS_ADMIN");
}

function isStaffOnly(roles: readonly string[]): boolean {
  return roles.includes("STAFF") && !roles.includes("MANAGER");
}

/**
 * 역할 → 노출 내비(섹션 그룹). 미상(에러 등)이면 MANAGER 전체로 폴백 — 서버 403이 최종 방어.
 * opts.hasTwin(기본 false)이면 MANAGER 관리소 운영에 단지 트윈을 더한다(하위호환).
 */
export function navForRoles(
  roles: readonly string[],
  opts: { hasTwin?: boolean } = {},
): readonly NavGroup[] {
  if (isSysAdmin(roles)) return SYS_ADMIN_NAV;
  if (isStaffOnly(roles)) return STAFF_NAV;
  return managerNav(opts.hasTwin ?? false);
}

/** 역할 → 첫 진입 경로. SYS_ADMIN=단지 관리 · STAFF=민원 · 그 외=AI 비서(H7-6 → H20-2 갱신). */
export function roleHome(roles: readonly string[]): string {
  if (isSysAdmin(roles)) return TENANTS.href;
  if (isStaffOnly(roles)) return INQUIRIES.href;
  return ASSISTANT.href;
}

/** 역할 → 사이드바 표시 라벨(H7-5 — 하드코딩 "관리자/관리사무소" 대체). */
export function roleLabel(roles: readonly string[]): string {
  if (isSysAdmin(roles)) return "시스템 관리자";
  if (roles.includes("MANAGER")) return "관리소장";
  if (roles.includes("STAFF")) return "직원";
  return "관리자";
}
