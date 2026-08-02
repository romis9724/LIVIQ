// 민원현황 표기 변환 — 순수 함수(테스트 대상).
// AI 도우미 현황 삭제(H20-2)로 비율·토큰 포매터도 함께 제거했다 — 쓰는 곳이 없다.

/** 정수 카운트 표기(천단위 구분). */
export function formatCount(value: number): string {
  return value.toLocaleString("ko-KR");
}

// DB 상태값 → 한글 라벨 + 막대 색(디자인 토큰만).
export const INQUIRY_STATUS_META: readonly {
  key: string;
  label: string;
  color: string;
}[] = [
  { key: "received", label: "접수됨", color: "var(--color-text-muted)" },
  { key: "assigned", label: "배정됨", color: "var(--color-accent)" },
  { key: "in_progress", label: "처리중", color: "var(--color-warning)" },
  { key: "done", label: "완료", color: "var(--color-success)" },
];

export const FACILITY_STATUS_META: readonly {
  key: string;
  label: string;
  color: string;
}[] = [
  { key: "normal", label: "정상", color: "var(--color-success)" },
  { key: "check", label: "점검", color: "var(--color-warning)" },
  { key: "fault", label: "장애", color: "var(--color-danger)" },
  { key: "risk", label: "위험", color: "var(--color-danger)" },
];

/** 상태 분포 → 막대 폭 % (최대값 기준 상대). 전부 0이면 0%. */
export function barWidth(count: number, counts: readonly number[]): string {
  const max = Math.max(...counts, 0);
  if (max === 0) return "0%";
  return `${Math.round((count / max) * 100)}%`;
}

/** 예산 사용 게이지 폭 % — used/budget, 0~100 클램프(초과해도 막대는 100%). */
export function budgetWidth(used: number, budget: number): string {
  if (budget <= 0) return "0%";
  return `${Math.min(100, Math.round((used / budget) * 100))}%`;
}
