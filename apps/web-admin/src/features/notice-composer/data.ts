// 공지 초안 스테퍼 순수 로직 — 키워드 칩 검증·신뢰도 매핑. 테스트 대상.

import type { ConfidenceStatus } from "@liviq/ui";

export const MAX_KEYWORDS = 10;

/** 신뢰도 배지가 answered(높음)로 넘어가는 하한. 그 아래는 review(검토 필요). */
export const CONFIDENCE_REVIEW_THRESHOLD = 0.6;

export type AddKeywordResult =
  | { ok: true; keywords: string[] }
  | { ok: false; reason: "empty" | "duplicate" | "max" };

/** 칩 추가 — 공백 트림 후 빈값·중복·상한(10) 을 거른다. 불변 반환. */
export function addKeyword(keywords: readonly string[], raw: string): AddKeywordResult {
  const value = raw.trim();
  if (!value) return { ok: false, reason: "empty" };
  if (keywords.length >= MAX_KEYWORDS) return { ok: false, reason: "max" };
  if (keywords.includes(value)) return { ok: false, reason: "duplicate" };
  return { ok: true, keywords: [...keywords, value] };
}

/** 인덱스로 칩 제거. 불변 반환. */
export function removeKeyword(keywords: readonly string[], index: number): string[] {
  return keywords.filter((_, i) => i !== index);
}

/** 초안 생성 가능 여부(1~10개). */
export function canGenerate(keywords: readonly string[]): boolean {
  return keywords.length >= 1 && keywords.length <= MAX_KEYWORDS;
}

export function confidenceStatus(confidence: number): ConfidenceStatus {
  return confidence >= CONFIDENCE_REVIEW_THRESHOLD ? "answered" : "review";
}
