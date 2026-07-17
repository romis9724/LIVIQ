// 운영 대시보드 표기 변환 — 순수 함수(테스트 대상). 서버는 0~1 분수·null 반환.

/** 0~1 분수 → "NN%". null(분모 0)은 "—"(지어내지 않음). */
export function formatPercent(rate: number | null): string {
  if (rate === null) return "—";
  return `${Math.round(rate * 100)}%`;
}

/** 평균 토큰 → 반올림 정수(천단위 구분). null은 "—". */
export function formatTokens(value: number | null): string {
  if (value === null) return "—";
  return Math.round(value).toLocaleString("ko-KR");
}

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
