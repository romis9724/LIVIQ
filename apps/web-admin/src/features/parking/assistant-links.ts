/**
 * AI 비서 → 주차장 대시보드 딥링크 (ADM-1 화면 연동 — 입주민 links.ts 와 같은 구조).
 *
 * `find_longterm_parking` 이 호출된 답변에 "주차장 3D에서 보기" CTA 를 띄우고, 장기주차
 * 면 번호를 쿼리스트링에 실어 3D 뷰에서 비콘 + 카메라 이동으로 보여준다. 면 번호는
 * **도구 결과 카드의 quote** 에서만 뽑는다 — 모델 본문 숫자는 근거가 아니다(규칙 1·8).
 */

import type { AssistantCitation } from "@liviq/ui";

/** 이 도구가 호출됐다 = 모델이 장기주차 단속 질의로 라우팅했다는 뜻(H19-3). */
export const LONGTERM_TOOL = "find_longterm_parking";

/** 도구 결과 카드 제목 — ai_core tools/library.py `_find_longterm_parking` 과 같아야 한다. */
export const LONGTERM_CARD_TITLE = "외부 차량 장기주차";

export function isLongtermParkingAnswer(toolPath: readonly string[] | undefined): boolean {
  return toolPath?.includes(LONGTERM_TOOL) ?? false;
}

/** 강조 상한 — URL 은 신뢰할 수 없는 입력이라 상한을 둔다(입주민 links 와 동일). */
const MAX_SPOTS = 10;
const SPOT_NO_PATTERN = /^[0-9A-Za-z-]{1,8}$/;
/** quote 한 줄 예: "- 098면 (31시간 경과)". */
const SPOT_IN_QUOTE = /(\d+)면/g;

function dedupe(nos: readonly string[]): string[] {
  return [...new Set(nos)].slice(0, MAX_SPOTS);
}

/** 장기주차 카드 quote → 면 번호(오래된 순 유지). 0건 quote 에는 면 번호가 없어 빈 배열. */
export function longtermSpotNos(citations: readonly AssistantCitation[]): string[] {
  const card = citations.find(
    (c) => c.documentId === null && c.documentTitle === LONGTERM_CARD_TITLE,
  );
  if (!card) return [];
  return dedupe([...card.quote.matchAll(SPOT_IN_QUOTE)].map((m) => m[1] as string));
}

/** 장기주차 면 → `/parking?spot=098,101&view=3d`. 면이 없으면 CTA 를 띄우지 않는 쪽이 맞다. */
export function buildLongtermParkingHref(spotNos: readonly string[]): string {
  const nos = dedupe(spotNos.filter((no) => SPOT_NO_PATTERN.test(no)));
  return nos.length > 0 ? `/parking?spot=${nos.join(",")}&view=3d` : "/parking";
}

/** `URLSearchParams` · Next 의 `ReadonlyURLSearchParams` 양쪽을 받는 최소 계약. */
interface QueryParams {
  get(key: string): string | null;
}

/** 쿼리스트링 → 비콘을 세울 면 번호(순서 유지 — 오래된 순 = 비콘 순번). */
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

/** 쿼리스트링 → 초기 보기 방식. "3d"만 인정(그 외는 2D). */
export function readViewParam(params: QueryParams): "2d" | "3d" {
  return params.get("view") === "3d" ? "3d" : "2d";
}
