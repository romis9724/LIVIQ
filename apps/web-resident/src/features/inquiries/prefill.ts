/**
 * 민원 접수 폼 프리필 딥링크 (ADR-0024).
 *
 * AI 비서는 민원을 만들지 않는다(절대규칙 8). 민원성 질의로 판정되면 질문 원문을
 * 쿼리스트링에 실은 링크만 렌더하고, 실제 접수는 사용자가 폼에서 확인·제출한다.
 * 본문에 AI 답변을 넣지 않는 이유도 같다 — 검증되지 않은 생성문이 민원 원문이 되면 안 된다.
 */

/** 폼 입력 상한 — SubmitForm 의 maxLength 와 동일해야 한다. */
export const INQUIRY_TITLE_MAX = 200;
export const INQUIRY_BODY_MAX = 4000;

/** CTA 제목은 질문을 짧게 줄여 보여준다(폼에서 수정 가능). */
const TITLE_SUMMARY_MAX = 40;

export interface ComposePrefill {
  isCompose: boolean;
  title: string;
  body: string;
}

export const EMPTY_PREFILL: ComposePrefill = { isCompose: false, title: "", body: "" };

/** `URLSearchParams` · Next 의 `ReadonlyURLSearchParams` 양쪽을 받는 최소 계약. */
interface QueryParams {
  get(key: string): string | null;
}

/** 질문 원문 → `/inquiries?compose=1&title=…&body=…`. 인코딩은 URLSearchParams 가 처리. */
export function buildComposeHref(question: string): string {
  const text = question.trim();
  const title =
    text.length > TITLE_SUMMARY_MAX ? `${text.slice(0, TITLE_SUMMARY_MAX)}…` : text;
  const params = new URLSearchParams({
    compose: "1",
    title,
    body: text.slice(0, INQUIRY_BODY_MAX),
  });
  return `/inquiries?${params.toString()}`;
}

/**
 * 쿼리스트링 → 접수 폼 초기값. URL 은 신뢰할 수 없는 입력이라 폼 상한으로 자른다.
 * `compose=1` 이 아니면 값이 있어도 전부 버린다.
 */
export function readComposePrefill(params: QueryParams): ComposePrefill {
  if (params.get("compose") !== "1") return EMPTY_PREFILL;
  return {
    isCompose: true,
    title: (params.get("title") ?? "").slice(0, INQUIRY_TITLE_MAX),
    body: (params.get("body") ?? "").slice(0, INQUIRY_BODY_MAX),
  };
}
