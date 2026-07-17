import type { ReviewCitation, ReviewStatus } from "@/lib/api";

export interface ConfidenceLook {
  color: string;
  icon: string;
  label: string;
}

/** 신뢰도(0~1) → 색/아이콘/라벨. 임계: <0.5 "매우 낮음"(위험) · <0.7 "낮음" · 이상 "보통". */
export function confidenceLook(conf: number): ConfidenceLook {
  if (conf >= 0.7) {
    return {
      color: "color-mix(in oklch, var(--color-success) 65%, var(--color-text))",
      icon: "✓",
      label: "보통",
    };
  }
  if (conf >= 0.5) {
    return {
      color: "color-mix(in oklch, var(--color-warning) 50%, var(--color-text))",
      icon: "!",
      label: "낮음",
    };
  }
  return { color: "var(--color-danger)", icon: "⚠", label: "매우 낮음" };
}

/** 신뢰도(0~1)를 0~100 정수 퍼센트로. null 이면 null. */
export function confidencePercent(conf: number | null): number | null {
  return conf === null ? null : Math.round(conf * 100);
}

/** 인용에서 표시 가능한 근거(문서명 있는 것)만 추린다 — 절대규칙 1 UI 표현. */
export function displayableCitations(citations: readonly ReviewCitation[]): ReviewCitation[] {
  return citations.filter((c) => Boolean(c.documentTitle));
}

export interface ReviewTab {
  id: ReviewStatus;
  label: string;
}

// 단일 status 파라미터에 1:1 매핑되는 탭(대기·승인·반려). "처리됨"을 세분해 병합 없이 조회.
export const REVIEW_TABS: readonly ReviewTab[] = [
  { id: "needs_review", label: "검수 대기" },
  { id: "approved", label: "승인됨" },
  { id: "rejected", label: "반려됨" },
];

/** ISO → "MM/DD HH:mm" (검수 큐는 시각까지 표시). */
export function reviewTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${mm}/${dd} ${hh}:${mi}`;
}
