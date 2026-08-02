/**
 * 평면도 딥링크 (H19-6 — 주차 `links.ts` 와 같은 구조).
 *
 * AI 비서가 `find_in_floor_plan` 을 호출하면 "평면도 보기" CTA 를 띄우고, 도구가 찾은
 * 위치 라벨을 쿼리스트링에 실어 평면도에서 강조한다. 라벨은 **도구 결과 카드의 quote**
 * 에서만 뽑는다 — 모델이 본문에 쓴 문구는 근거가 아니다(규칙 1·8). 동의어 해석
 * (두꺼비집 → 분전함)은 서버 도구가 이미 끝냈으므로 여기서는 다시 하지 않는다.
 */

import type { AssistantCitation } from "@liviq/ui";

/** 이 도구가 호출됐다 = 모델이 세대 평면도 위치 질의로 라우팅했다는 뜻. */
export const FLOOR_PLAN_TOOL = "find_in_floor_plan";

/** 도구 결과 카드 제목 — ai_core tools/floor_plan.py 의 ToolCard(title=...) 와 같아야 한다. */
export const FLOOR_PLAN_CARD_TITLE = "평면도 위치";

export function isFloorPlanAnswer(toolPath: readonly string[] | undefined): boolean {
  return toolPath?.includes(FLOOR_PLAN_TOOL) ?? false;
}

/** 강조 라벨 상한 — URL 은 신뢰할 수 없는 입력이라 개수·길이·문자를 모두 제한한다. */
const MAX_LABELS = 5;
const MAX_LABEL_LENGTH = 24;

/** 허용 문자: 한글·영숫자·공백·가운뎃점·하이픈. 구분자(,)와 기호는 버린다. */
const LABEL_PATTERN = /^[\p{L}\p{N} ·-]+$/u;

/** quote 한 줄 예: "거실 콘센트 3곳: 위쪽·왼쪽·오른쪽" → "거실 콘센트". */
const LOCATION_SEGMENT = /^(.+?)\s+\d+곳:/;

function dedupe(labels: readonly string[]): string[] {
  return [...new Set(labels)].slice(0, MAX_LABELS);
}

function isSafeLabel(label: string): boolean {
  return label.length > 0 && label.length <= MAX_LABEL_LENGTH && LABEL_PATTERN.test(label);
}

/**
 * 도구 결과 인용에서 강조할 위치 라벨 추출. 문서 인용(documentId 있음)은 건너뛴다 —
 * 도구 카드는 `document_id: null` + 카드 제목으로 식별된다(assistant SSE 계약).
 * 방 질의("거실 위치")는 마커가 아니라 방 라벨이라 뽑지 않는다.
 */
export function deviceLabelsFromCitations(citations: readonly AssistantCitation[]): string[] {
  const card = citations.find(
    (c) => c.documentId === null && c.documentTitle === FLOOR_PLAN_CARD_TITLE,
  );
  if (!card) return [];
  const labels = card.quote
    .split(";")
    .map((segment) => LOCATION_SEGMENT.exec(segment.trim())?.[1]?.trim())
    .filter((label): label is string => label !== undefined && isSafeLabel(label));
  return dedupe(labels);
}

/** 라벨 → `/floor-plan?device=거실%20콘센트,주방%20콘센트`. 라벨이 없으면 쿼리 없이 `/floor-plan`. */
export function buildFloorPlanHref(labels: readonly string[]): string {
  const safe = dedupe(labels.map((l) => l.trim()).filter(isSafeLabel));
  if (safe.length === 0) return "/floor-plan";
  return `/floor-plan?device=${safe.map(encodeURIComponent).join(",")}`;
}

/** `URLSearchParams` · Next 의 `ReadonlyURLSearchParams` 양쪽을 받는 최소 계약. */
interface QueryParams {
  get(key: string): string | null;
}

/** 쿼리스트링 → 강조할 라벨. URL 은 신뢰할 수 없는 입력이라 형식·개수를 검증한다. */
export function readDeviceParam(params: QueryParams): string[] {
  const raw = params.get("device");
  if (!raw) return [];
  return dedupe(
    raw
      .split(",")
      .map((label) => label.trim())
      .filter(isSafeLabel),
  );
}
