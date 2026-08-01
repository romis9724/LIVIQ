/**
 * 도구 결과 구조화 페이로드 (H18-3 ② — `citation.data`, ADR-0025 §6).
 *
 * 서버(ai_core/tools/*.py 의 `_data`·`_fee_data`·`_facility_data`)가 **확정한 값**을 그대로
 * 싣고 온다. 여기서 하는 일은 렌더러를 고르기 위한 `kind` 분기와 최소 형태 검사뿐이다 —
 * 숫자를 다시 계산하지 않는다(규칙 5·8). 모르는 `kind` 는 조용히 버려서 서버가 새 블록을
 * 추가해도 구버전 화면이 깨지지 않게 한다(전방 호환).
 */

import type { Citation } from "./api";

export interface FeeRow {
  name: string;
  amount: number;
}

export interface FeeTableData {
  kind: "fee_table";
  period: string;
  rows: FeeRow[];
  total: number;
  prevTotal: number | null;
  diff: number | null;
}

export interface ParkingSpot {
  no: string;
  /** 자리 종류(일반·전기차 등) — 서버 라벨 그대로. */
  kind: string;
  distanceM: number;
}

export interface ParkingSpotsData {
  kind: "parking_spots";
  spots: ParkingSpot[];
}

export interface FacilityItem {
  name: string;
  status: string;
  code: string | null;
}

export interface FacilityStatusData {
  kind: "facility_status";
  total: number;
  /** 상태 라벨 → 대수. 서버가 센 값. */
  statusCounts: Array<{ status: string; count: number }>;
  items: FacilityItem[];
}

export interface InquiryCase {
  title: string;
  category: string;
  status: string;
  resolution: string;
  isMine: boolean;
}

export interface InquiryCasesData {
  kind: "inquiry_cases";
  cases: InquiryCase[];
}

export type StructuredData =
  | FeeTableData
  | ParkingSpotsData
  | FacilityStatusData
  | InquiryCasesData;

type Raw = Record<string, unknown>;

function asRecord(value: unknown): Raw | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Raw)
    : null;
}

function asRows(value: unknown): Raw[] {
  if (!Array.isArray(value)) return [];
  return (value as unknown[]).flatMap((v): Raw[] => {
    const row = asRecord(v);
    return row ? [row] : [];
  });
}

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const numOrNull = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

/**
 * `citation.data` → 렌더 가능한 구조화 블록. 알 수 없는 형태·kind 는 null(= 텍스트 인용만).
 * 와이어 JSON 이라 필드 유무를 신뢰하지 않는다 — 빠진 값은 빈 문자열·0 으로 떨어진다.
 */
export function toStructured(data: unknown): StructuredData | null {
  const raw = asRecord(data);
  if (!raw) return null;
  switch (raw.kind) {
    case "fee_table":
      return {
        kind: "fee_table",
        period: str(raw.period),
        rows: asRows(raw.rows).map((r) => ({ name: str(r.name), amount: num(r.amount) })),
        total: num(raw.total),
        prevTotal: numOrNull(raw.prev_total),
        diff: numOrNull(raw.diff),
      };
    case "parking_spots":
      return {
        kind: "parking_spots",
        spots: asRows(raw.spots).map((s) => ({
          no: str(s.no),
          kind: str(s.kind),
          distanceM: num(s.distance_m),
        })),
      };
    case "facility_status": {
      const counts = asRecord(raw.status_counts) ?? {};
      return {
        kind: "facility_status",
        total: num(raw.total),
        statusCounts: Object.entries(counts).map(([status, count]) => ({
          status,
          count: num(count),
        })),
        items: asRows(raw.items).map((i) => ({
          name: str(i.name),
          status: str(i.status),
          code: typeof i.code === "string" ? i.code : null,
        })),
      };
    }
    case "inquiry_cases":
      return {
        kind: "inquiry_cases",
        cases: asRows(raw.cases).map((c) => ({
          title: str(c.title),
          category: str(c.category),
          status: str(c.status),
          resolution: str(c.resolution),
          isMine: c.is_mine === true,
        })),
      };
    default:
      return null;
  }
}

/** 인용 목록에서 렌더 가능한 블록만 뽑는다. `ref` 는 어느 출처의 데이터인지 되짚는 키. */
export function structuredBlocks(
  citations: readonly Citation[],
): Array<{ ref: number; data: StructuredData }> {
  return citations.flatMap((c) => {
    const data = toStructured(c.data);
    return data ? [{ ref: c.ref, data }] : [];
  });
}
