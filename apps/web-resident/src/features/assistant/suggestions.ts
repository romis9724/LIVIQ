/**
 * 다음 행동 제안 칩 (H18-3 ④ — `done.suggestions`, ADR-0025 §7).
 *
 * 칩을 누르면 그 문구로 **새 질문을 보낸다**. 그래서 "이동"이 본질인 제안은 칩이 아니라
 * 기존 CTA 링크(prefill.ts·links.ts)가 담당한다 — "민원 접수하기"를 질문으로 보내면 AI 가
 * *접수 방법*을 설명할 뿐 폼이 열리지 않는다. 같은 행동이 칩·버튼으로 겹치면 **칩을 지운다**.
 */

/** 이미 CTA 버튼으로 나가는 제안 문구 — ai_core/suggestions.py 의 라벨과 같아야 한다. */
export const INQUIRY_SUGGESTION = "민원 접수하기";
export const PARKING_SUGGESTION = "주차맵에서 보기";

export interface RenderedCtas {
  /** "민원 접수하기" 링크를 이미 렌더했는가. */
  inquiry: boolean;
  /** "주차위치 보기" 링크를 이미 렌더했는가. */
  parking: boolean;
}

/**
 * 칩으로 남길 제안. 렌더된 CTA 와 겹치는 문구를 빼고 순서·중복 제거 상태를 유지한다.
 * (개수 상한은 서버가 3개로 이미 잘라서 보낸다 — 여기서 또 자르지 않는다.)
 */
export function visibleSuggestions(
  suggestions: readonly string[],
  ctas: RenderedCtas,
): string[] {
  const hidden = new Set<string>();
  if (ctas.inquiry) hidden.add(INQUIRY_SUGGESTION);
  if (ctas.parking) hidden.add(PARKING_SUGGESTION);
  return [...new Set(suggestions)].filter((s) => !hidden.has(s));
}
