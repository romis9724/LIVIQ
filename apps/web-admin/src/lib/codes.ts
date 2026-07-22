// 공통 코드(H8-4) 소비 헬퍼 — 폼 select 선택지·목록 라벨 매핑. 순수 함수(테스트 대상).
// 공지 분류(NOTICE_CATEGORY)·문서 분류(DOC_CATEGORY)를 폼에서 참조할 때 재사용.

import type { Code, CodeGroup } from "./api";

export const NOTICE_CATEGORY_GROUP = "NOTICE_CATEGORY";
export const DOC_CATEGORY_GROUP = "DOC_CATEGORY";

export interface CodeOption {
  id: string;
  label: string;
}

/** sort_order 오름차순, 동률이면 code 사전순(서버 정렬과 동일). 불변. */
function bySort(a: Code, b: Code): number {
  if (a.sortOrder !== b.sortOrder) return a.sortOrder - b.sortOrder;
  return a.code.localeCompare(b.code);
}

/** 그룹 키로 소속 코드를 찾는다(없으면 빈 배열). */
function codesOf(groups: readonly CodeGroup[], groupKey: string): Code[] {
  return groups.find((g) => g.groupKey === groupKey)?.codes ?? [];
}

/** select 선택지 — 지정 그룹의 active 코드만, 정렬해 {id, label} 로. */
export function codeOptions(groups: readonly CodeGroup[], groupKey: string): CodeOption[] {
  return codesOf(groups, groupKey)
    .filter((c) => c.active)
    .sort(bySort)
    .map((c) => ({ id: c.id, label: c.label }));
}

/**
 * id → 라벨 매핑(목록 표시용). 비활성 코드도 포함 — 과거 코드 참조 항목도 라벨을 보이게.
 */
export function codeLabelMap(groups: readonly CodeGroup[], groupKey: string): Map<string, string> {
  return new Map(codesOf(groups, groupKey).map((c) => [c.id, c.label]));
}
