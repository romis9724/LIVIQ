/**
 * 화면 카탈로그 — "LIVIQ 전체 화면" 디자인의 DCLogic 데이터를 코드로 옮긴 단일 출처.
 * 입주민 6 + 관리자 6 화면. 우선순위(P0~P2)와 라우트를 함께 보관한다.
 */
export type Priority = "P0" | "P1" | "P2";
export type AppArea = "resident" | "admin";

export interface ScreenItem {
  icon: string;
  title: string;
  desc: string;
  href: string;
  priority: Priority;
  area: AppArea;
}

export const RESIDENT_SCREENS: readonly ScreenItem[] = [
  { icon: "💬", title: "AI 비서", desc: "출처 기반 응대·스트리밍·폴백", href: "/assistant", priority: "P0", area: "resident" },
  { icon: "🏠", title: "홈", desc: "단지 요약·관리비·바로가기", href: "/home", priority: "P0", area: "resident" },
  { icon: "📢", title: "공지", desc: "말머리·중요 배지·상세", href: "/notices", priority: "P1", area: "resident" },
  { icon: "🛠", title: "민원·하자", desc: "사진+AI 분류·타임라인", href: "/inquiries", priority: "P1", area: "resident" },
  { icon: "🧾", title: "관리비", desc: "추이·항목·왜 올랐나 AI", href: "/fees", priority: "P1", area: "resident" },
  { icon: "👤", title: "나", desc: "활동·설정·개인정보 동의", href: "/me", priority: "P2", area: "resident" },
];

export const ADMIN_SCREENS: readonly ScreenItem[] = [
  { icon: "✅", title: "AI 검수 큐", desc: "신뢰도 검토·승인/반려", href: "/admin/review-queue", priority: "P0", area: "admin" },
  { icon: "📢", title: "공지 초안 작성", desc: "키워드→초안→검수→발송", href: "/admin/notices/new", priority: "P0", area: "admin" },
  { icon: "📊", title: "대시보드", desc: "자동해결률·환각률·토큰비용", href: "/admin/dashboard", priority: "P1", area: "admin" },
  { icon: "🛠", title: "민원 관리", desc: "AI 분류·우선순위·배정", href: "/admin/inquiries", priority: "P1", area: "admin" },
  { icon: "📁", title: "문서 관리", desc: "업로드·공개범위·색인 상태", href: "/admin/documents", priority: "P1", area: "admin" },
  { icon: "🏢", title: "시설 관리", desc: "상태·AI 원인 후보", href: "/admin/facilities", priority: "P2", area: "admin" },
];

/** 우선순위 → 라벨 색상 토큰 (디자인 DCLogic.pc() 이식). */
export function priorityColor(priority: Priority): string {
  if (priority === "P0") return "var(--color-accent)";
  if (priority === "P1") return "color-mix(in oklch, var(--color-success) 65%, var(--color-text))";
  return "var(--color-text-muted)";
}
