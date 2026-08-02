/**
 * 주차맵 딥링크 (H17-2 — 민원 prefill 과 같은 구조).
 *
 * AI 비서가 `find_nearest_available_parking` 을 호출하면 "주차위치 보기" CTA 를 띄우고,
 * 추천 면 번호를 쿼리스트링에 실어 지도에서 강조한다. 면 번호는 **도구 결과 카드의 quote**
 * 에서만 뽑는다 — 모델이 본문에 쓴 숫자는 근거가 아니다(규칙 1·8).
 */

import type { AssistantCitation } from "@liviq/ui";

/** 이 도구가 호출됐다 = 모델이 빈자리 질의로 라우팅했다는 뜻. */
export const PARKING_TOOL = "find_nearest_available_parking";

/** 내 차 위치(H19-2) — 답변에 나온 면을 지도에서 강조하는 동선은 빈자리와 같다. */
export const MY_VEHICLE_TOOL = "find_my_vehicle";

/** 도구 결과 카드 제목 — ai_core tools/parking.py 의 `_CARD_TITLE`·`_MY_CARD_TITLE` 과 같아야 한다. */
export const PARKING_CARD_TITLE = "가까운 빈 주차자리";
export const MY_VEHICLE_CARD_TITLE = "내 차량 위치";

const SPOT_CARD_TITLES: readonly string[] = [PARKING_CARD_TITLE, MY_VEHICLE_CARD_TITLE];

/** 주차 도구가 하나라도 호출됐으면 "주차위치 보기" CTA 를 띄운다. */
export function isParkingAnswer(toolPath: readonly string[] | undefined): boolean {
  return toolPath?.some((t) => t === PARKING_TOOL || t === MY_VEHICLE_TOOL) ?? false;
}

/** 강조 상한 — 도구는 top_k 3면을 주지만 URL 은 신뢰할 수 없는 입력이라 상한을 둔다. */
const MAX_SPOTS = 10;

/** 면 번호 허용 문자 — 배치도 `spots[].no`("012" 등). 그 외는 버린다. */
const SPOT_NO_PATTERN = /^[0-9A-Za-z-]{1,8}$/;

/** quote 한 줄 예: "① 012면 (일반, 약 34m)". 숫자+"면" 만 뽑는다. */
const SPOT_IN_QUOTE = /(\d+)면/g;

function dedupe(nos: readonly string[]): string[] {
  return [...new Set(nos)].slice(0, MAX_SPOTS);
}

/**
 * 도구 결과 인용에서 추천 면 번호 추출. 문서 인용(documentId 있음)은 건너뛴다 —
 * 도구 카드는 `document_id: null` + 카드 제목으로 식별된다(assistant SSE 계약).
 * 빈자리가 없을 때의 quote 에는 면 번호가 없어 자연히 빈 배열이 된다.
 */
export function spotNosFromCitations(citations: readonly AssistantCitation[]): string[] {
  const card = citations.find(
    (c) => c.documentId === null && SPOT_CARD_TITLES.includes(c.documentTitle),
  );
  if (!card) return [];
  return dedupe([...card.quote.matchAll(SPOT_IN_QUOTE)].map((m) => m[1] as string));
}

/** 추천 면 → `/parking?spot=012,034`. 면이 없으면 쿼리 없이 `/parking`. */
export function buildParkingHref(spotNos: readonly string[]): string {
  const nos = dedupe(spotNos.filter((no) => SPOT_NO_PATTERN.test(no)));
  return nos.length > 0 ? `/parking?spot=${nos.join(",")}` : "/parking";
}

/** `URLSearchParams` · Next 의 `ReadonlyURLSearchParams` 양쪽을 받는 최소 계약. */
interface QueryParams {
  get(key: string): string | null;
}

/** 쿼리스트링 → 강조할 면 번호. URL 은 신뢰할 수 없는 입력이라 형식·개수를 검증한다. */
export function readSpotParam(params: QueryParams): string[] {
  const raw = params.get("spot");
  if (!raw) return [];
  return dedupe(
    raw
      .split(",")
      .map((no) => no.trim())
      .filter((no) => SPOT_NO_PATTERN.test(no)),
  );
}
