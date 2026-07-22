// 코드 관리 순수 로직 — 평면 코드 → 2단계 트리, group_key·코드 값 검증. 테스트 대상.
// 렌더·네트워크와 무관한 계산만 담는다. 계층 유효성(순환·같은 그룹)은 서버가 최종 방어.

import type { Code } from "@/lib/api";

/** 트리 노드 — 부모 코드 + 정렬된 자식(2단계 한정). */
export interface CodeNode extends Code {
  children: Code[];
}

/** sort_order 오름차순, 동률이면 code 사전순(서버 정렬과 동일, 방어적 재정렬). 불변. */
function bySort(a: Code, b: Code): number {
  if (a.sortOrder !== b.sortOrder) return a.sortOrder - b.sortOrder;
  return a.code.localeCompare(b.code);
}

/**
 * 평면 코드 배열 → 2단계 트리. parent_id 없는 코드가 최상위, 나머지는 부모 아래.
 * 부모가 목록에 없는 고아 코드는 최상위로 승격(데이터 유실 방지). 불변.
 */
export function buildCodeTree(codes: readonly Code[]): CodeNode[] {
  const byParent = new Map<string, Code[]>();
  for (const code of codes) {
    if (code.parentId === null) continue;
    const siblings = byParent.get(code.parentId) ?? [];
    byParent.set(code.parentId, [...siblings, code]);
  }
  const ids = new Set(codes.map((c) => c.id));
  const roots = codes.filter((c) => c.parentId === null || !ids.has(c.parentId));
  return [...roots].sort(bySort).map((root) => ({
    ...root,
    children: [...(byParent.get(root.id) ?? [])].sort(bySort),
  }));
}

/** 그룹 키 규칙 — 대문자로 시작, 대문자·숫자·언더스코어만(예: FEE_KIND). */
export const GROUP_KEY_PATTERN = /^[A-Z][A-Z0-9_]*$/;

/** group_key 검증. 통과 시 null, 실패 시 사용자 안내 메시지. */
export function validateGroupKey(key: string): string | null {
  const trimmed = key.trim();
  if (!trimmed) return "그룹 키를 입력하세요.";
  if (!GROUP_KEY_PATTERN.test(trimmed)) {
    return "대문자·숫자·언더스코어만 사용하고 대문자로 시작하세요. (예: FEE_KIND)";
  }
  return null;
}

/** 코드 값 검증 — 비어 있지 않으면 통과. */
export function validateCodeValue(code: string): string | null {
  return code.trim() ? null : "코드 값을 입력하세요.";
}

/** 라벨 필수 검증. */
export function validateLabel(label: string): string | null {
  return label.trim() ? null : "표시 이름을 입력하세요.";
}
