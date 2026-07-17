import type { Facility, FacilityStatus } from "@/lib/api";

// DB 상태(normal|check|fault|risk) → 라벨 + CSS 접미사(기존 facilities.css 재사용).
// css 는 --ok/--check/--fault/--risk 를 쓰므로 normal→ok 로 매핑.
export const STATUS_META: Record<
  FacilityStatus,
  { label: string; css: "ok" | "check" | "fault" | "risk"; icon: string }
> = {
  normal: { label: "정상", css: "ok", icon: "🟢" },
  check: { label: "점검", css: "check", icon: "🟡" },
  fault: { label: "장애", css: "fault", icon: "🔴" },
  risk: { label: "위험", css: "risk", icon: "⛔" },
};

export const STATUS_ORDER: readonly FacilityStatus[] = ["normal", "check", "fault", "risk"];

export type FilterId = "all" | FacilityStatus;
export const FILTERS: readonly { id: FilterId; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "normal", label: "정상" },
  { id: "check", label: "점검" },
  { id: "fault", label: "장애" },
  { id: "risk", label: "위험" },
];

/** 필터별 개수 집계 — all 은 전체 기준. */
export function countByStatus(facilities: readonly Facility[]): Record<FilterId, number> {
  const counts: Record<FilterId, number> = { all: facilities.length, normal: 0, check: 0, fault: 0, risk: 0 };
  for (const f of facilities) counts[f.status] += 1;
  return counts;
}

/** 설비 등록 폼 검증 — 이름 필수(공백 불가). 순수 함수(기존 data.ts 패턴, Zod 미사용). */
export function validateFacilityName(name: string): string | null {
  if (!name.trim()) return "설비 이름을 입력하세요.";
  if (name.trim().length > 200) return "이름은 200자 이하여야 합니다.";
  return null;
}

/** 장애·정비 기록 필수 텍스트 검증(증상/작업 내용). */
export function validateRequiredText(value: string, field: string): string | null {
  if (!value.trim()) return `${field}을(를) 입력하세요.`;
  if (value.trim().length > 4000) return `${field}은(는) 4000자 이하여야 합니다.`;
  return null;
}

/** ISO → "YYYY.MM.DD". 없으면 대시. */
export function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const yy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yy}.${mm}.${dd}`;
}
