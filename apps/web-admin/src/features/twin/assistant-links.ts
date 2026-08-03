/**
 * AI 비서 → 트윈 대시보드 세대 평면도 딥링크 (H20-17 — 주차 `assistant-links.ts` 와 같은 구조).
 *
 * `find_household_devices` 가 호출된 답변에 "평면도 보기" CTA 를 띄우고, **도구가 확정한**
 * 동·호수·강조 라벨을 쿼리스트링에 실어 그 세대 평면도를 열고 마커를 강조한다.
 * 값은 `citation.data`(서버 확정 페이로드) 에서만 뽑는다 — 모델이 본문에 쓴 문구·숫자는
 * 근거가 아니다(규칙 1·8). 동의어 해석(두꺼비집 → 분전함)은 서버 도구가 이미 끝냈다.
 */

import type { AssistantCitation } from "@liviq/ui";

/** 이 도구가 호출됐다 = 서버가 동·호수를 확정하고 그 세대 평면도를 조회했다는 뜻. */
export const HOUSEHOLD_DEVICES_TOOL = "find_household_devices";

export function isHouseholdDevicesAnswer(toolPath: readonly string[] | undefined): boolean {
  return toolPath?.includes(HOUSEHOLD_DEVICES_TOOL) ?? false;
}

/** URL 은 신뢰할 수 없는 입력이라 개수·길이·문자를 모두 제한한다(입주민 links 와 동일). */
const MAX_LABELS = 5;
const MAX_LABEL_LENGTH = 24;
/** 허용 문자: 한글·영숫자·공백·가운뎃점·하이픈. */
const LABEL_PATTERN = /^[\p{L}\p{N} ·-]+$/u;
/** 동 이름·호수 — `parse_unit`(서버)이 숫자만 내보낸다. */
const DONG_PATTERN = /^\d{1,4}$/;
const MAX_HO = 9999;

export interface HouseholdDeviceTarget {
  dong: string;
  ho: number;
  /** 평면도에서 강조할 마커 라벨("거실 콘센트"). 비어 있을 수 있다. */
  labels: string[];
}

function isSafeLabel(label: string): boolean {
  return label.length > 0 && label.length <= MAX_LABEL_LENGTH && LABEL_PATTERN.test(label);
}

function safeLabels(values: readonly unknown[]): string[] {
  const labels = values
    .filter((v): v is string => typeof v === "string")
    .map((v) => v.trim())
    .filter(isSafeLabel);
  return [...new Set(labels)].slice(0, MAX_LABELS);
}

function isSafeHo(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0 && value <= MAX_HO;
}

/**
 * 도구 결과 인용에서 조회 대상 세대와 강조 라벨을 뽑는다. 문서 인용(documentId 있음)은
 * 건너뛴다 — 도구 카드는 `documentId: null` 이고 `data.kind` 로 식별된다(SSE 계약).
 */
export function householdDeviceTarget(
  citations: readonly AssistantCitation[],
): HouseholdDeviceTarget | null {
  for (const citation of citations) {
    if (citation.documentId !== null) continue;
    const data = citation.data;
    if (typeof data !== "object" || data === null) continue;
    const raw = data as Record<string, unknown>;
    if (raw.kind !== "home_devices") continue;
    if (typeof raw.dong !== "string" || !DONG_PATTERN.test(raw.dong)) continue;
    if (!isSafeHo(raw.ho)) continue;
    return {
      dong: raw.dong,
      ho: raw.ho,
      labels: safeLabels(Array.isArray(raw.labels) ? raw.labels : []),
    };
  }
  return null;
}

/** 대상 세대 → `/twin?dong=402&ho=201&device=거실%20콘센트`. 라벨이 없으면 세대만 연다. */
export function buildTwinHouseholdHref(target: HouseholdDeviceTarget): string {
  const query = new URLSearchParams({ dong: target.dong, ho: String(target.ho) });
  const labels = safeLabels(target.labels);
  if (labels.length > 0) query.set("device", labels.join(","));
  return `/twin?${query.toString()}`;
}

/** `URLSearchParams` · Next 의 `ReadonlyURLSearchParams` 양쪽을 받는 최소 계약. */
interface QueryParams {
  get(key: string): string | null;
}

/** 쿼리스트링 → 열어 줄 세대. 형식이 어긋나면 null(딥링크 없이 평소의 트윈 화면). */
export function readUnitParams(params: QueryParams): { dong: string; ho: number } | null {
  const dong = params.get("dong");
  const ho = Number(params.get("ho"));
  if (!dong || !DONG_PATTERN.test(dong) || !isSafeHo(ho)) return null;
  return { dong, ho };
}

/** 쿼리스트링 → 강조할 라벨. URL 은 신뢰할 수 없는 입력이라 형식·개수를 검증한다. */
export function readDeviceParam(params: QueryParams): string[] {
  const raw = params.get("device");
  if (!raw) return [];
  return safeLabels(raw.split(","));
}
