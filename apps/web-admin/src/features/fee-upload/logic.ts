/**
 * 관리비 업로드 순수 로직 — 백엔드 연동 전 결정적 시드(랜덤 금지).
 * 관리비는 엑셀 업로드가 단일 출처이며 AI는 계산·부과에 관여하지 않는다(ADR-0006).
 * 여기서는 목업 세대 데이터 생성·검증 결과 분기·요약/전월 대비 계산만 담당한다.
 */

export interface FeeItem {
  key: FeeItemKey;
  label: string;
}

export const FEE_ITEMS = [
  { key: "general", label: "일반관리비" },
  { key: "cleaning", label: "청소비" },
  { key: "security", label: "경비비" },
  { key: "elevator", label: "승강기유지비" },
  { key: "heating", label: "난방비" },
  { key: "water", label: "수도료" },
] as const satisfies readonly FeeItem[];

export type FeeItemKey =
  | "general"
  | "cleaning"
  | "security"
  | "elevator"
  | "heating"
  | "water";

export interface HouseholdFee {
  dong: string; // "101"
  ho: string; // "1502" (15층 2호)
  items: Record<FeeItemKey, number>; // 원 단위
  total: number;
}

/** 파일럿 단지 규모: 101~103동 × 15층 × 2호 = 90세대. */
export const DONGS = ["101", "102", "103"] as const;
const FLOORS = 15;
const UNITS = 2;

const BASE: Record<FeeItemKey, number> = {
  general: 62000,
  cleaning: 18000,
  security: 41000,
  elevator: 9000,
  heating: 73000,
  water: 15000,
};

/** 세대별 변동 폭(원). 난방비가 세대차가 가장 크게 보이도록. */
const SPREAD: Record<FeeItemKey, number> = {
  general: 4000,
  cleaning: 1000,
  security: 2000,
  elevator: 500,
  heating: 12000,
  water: 3000,
};

/** 동·호에서 0~999 결정적 시드 도출. */
function seedOf(dong: string, ho: string): number {
  const s = `${dong}-${ho}`;
  let acc = 7;
  for (let i = 0; i < s.length; i += 1) {
    acc = (acc * 31 + s.charCodeAt(i)) >>> 0;
  }
  return acc % 1000;
}

/** 항목별 금액 = 기준액 + 시드 기반 변동(100원 단위). */
function itemAmount(key: FeeItemKey, seed: number): number {
  const delta = Math.round(((seed / 1000) * SPREAD[key]) / 100) * 100;
  return BASE[key] + delta;
}

function buildHouseholds(): HouseholdFee[] {
  const out: HouseholdFee[] = [];
  for (const dong of DONGS) {
    for (let floor = 1; floor <= FLOORS; floor += 1) {
      for (let unit = 1; unit <= UNITS; unit += 1) {
        const ho = `${floor}${String(unit).padStart(2, "0")}`;
        const seed = seedOf(dong, ho);
        const items = {} as Record<FeeItemKey, number>;
        let total = 0;
        for (const { key } of FEE_ITEMS) {
          const amt = itemAmount(key, seed);
          items[key] = amt;
          total += amt;
        }
        out.push({ dong, ho, items, total });
      }
    }
  }
  return out;
}

export const HOUSEHOLDS: readonly HouseholdFee[] = buildHouseholds();
export const HOUSEHOLD_COUNT = HOUSEHOLDS.length; // 90

export interface FeeSummary {
  count: number;
  total: number;
  average: number;
}

/** 세대 목록의 세대 수·합계·평균(원). */
export function feeSummary(households: readonly HouseholdFee[]): FeeSummary {
  const total = households.reduce((sum, h) => sum + h.total, 0);
  const count = households.length;
  const average = count === 0 ? 0 : Math.round(total / count);
  return { count, total, average };
}

/** 전월 대비 증감률(%). 이전값 0이면 0. 반올림 정수. */
export function percentDelta(current: number, previous: number): number {
  if (previous === 0) return 0;
  return Math.round(((current - previous) / previous) * 100);
}

const CURRENT_TOTAL = feeSummary(HOUSEHOLDS).total;
/** 미리보기 "전월 대비" 표시용 고정 기준(약 +3%가 되도록). */
export const PREV_MONTH_TOTAL = Math.round(CURRENT_TOTAL / 1.03);

export interface ValidationIssue {
  row: number;
  column: string;
  reason: string;
}

export interface ValidationResult {
  ok: boolean;
  validatedCount: number;
  missingCount: number;
  issues: readonly ValidationIssue[];
}

/**
 * 업로드 검증 결과. 데모 분기: 파일명에 'error'가 포함되면 오류 리포트를 돌려준다.
 * 오류가 있으면 ok=false → 미리보기·확정으로 진행 불가.
 */
export function validateUpload(fileName: string): ValidationResult {
  const hasError = /error/i.test(fileName);
  if (hasError) {
    return {
      ok: false,
      validatedCount: HOUSEHOLD_COUNT - 2,
      missingCount: 2,
      issues: [
        { row: 12, column: "금액", reason: "금액이 음수입니다" },
        { row: 34, column: "동·호", reason: "동·호가 중복됩니다" },
      ],
    };
  }
  return { ok: true, validatedCount: HOUSEHOLD_COUNT, missingCount: 0, issues: [] };
}

/** 미리보기 표 상위 n행. */
export function previewRows(
  households: readonly HouseholdFee[],
  n = 5,
): readonly HouseholdFee[] {
  return households.slice(0, n);
}

export interface UploadRecord {
  month: string; // "2026-07"
  revision: number; // 같은 달 재업로드 시 증가(전체 교체)
  uploadedAt: string; // "2026-07-05 16:40"
  householdCount: number;
  total: number;
}

/** 업로드 이력 — 2026-07은 재업로드로 revision 2까지 존재(전체 교체 이력). */
export const UPLOAD_HISTORY: readonly UploadRecord[] = [
  { month: "2026-07", revision: 2, uploadedAt: "2026-07-05 16:40", householdCount: 90, total: CURRENT_TOTAL },
  { month: "2026-07", revision: 1, uploadedAt: "2026-07-05 14:22", householdCount: 90, total: CURRENT_TOTAL - 128000 },
  { month: "2026-06", revision: 1, uploadedAt: "2026-06-04 10:05", householdCount: 90, total: Math.round(CURRENT_TOTAL * 0.98) },
  { month: "2026-05", revision: 1, uploadedAt: "2026-05-06 11:30", householdCount: 90, total: Math.round(CURRENT_TOTAL * 0.965) },
];

/** 부과 현황 탭 월 셀렉트 옵션. 2026-04는 데이터 없음(EmptyState 데모). */
export const STATUS_MONTHS = ["2026-07", "2026-06", "2026-05", "2026-04"] as const;

/** 해당 월의 최신(최고 revision) 업로드 기록. 없으면 undefined. */
export function latestRecord(month: string): UploadRecord | undefined {
  return UPLOAD_HISTORY.filter((r) => r.month === month).sort(
    (a, b) => b.revision - a.revision,
  )[0];
}

/** 세대 조회 — 동(all|101…)·호 끝2자리(all|01|02) 필터 후 상위 limit행. */
export function lookupHouseholds(
  dong: string,
  unit: string,
  limit = 10,
): readonly HouseholdFee[] {
  return HOUSEHOLDS.filter(
    (h) =>
      (dong === "all" || h.dong === dong) &&
      (unit === "all" || h.ho.endsWith(unit)),
  ).slice(0, limit);
}

/** 1000단위 구분 기호. toLocaleString ICU 의존을 피해 결정적으로 포맷. */
export function groupDigits(n: number): string {
  return Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** 원 단위 금액 표기. 예: 218000 → "218,000원". */
export function formatWon(n: number): string {
  return `${groupDigits(n)}원`;
}

/** "2026-07" → "2026년 7월". */
export function monthLabel(month: string): string {
  const [year, mon] = month.split("-");
  return `${year}년 ${Number(mon)}월`;
}
