/**
 * 관리비 고지서 트리 구성 — 순수 헬퍼(표시 전용, 규칙 5).
 * 서버가 준 순서 보존 리스트(name·level·amount)를 대분류(level 0) 그룹으로 묶고,
 * 고지서에 노출하지 않는 누적지표(충당금잔액·적립요율)를 걸러낸다. 금액은 서버 값 그대로.
 */

export interface BreakdownRow {
  name: string;
  level: number;
  amount: number;
}

/** 고지서에서 숨기는 누적지표 행(차감·부과 항목 아님). */
const HIDDEN_NAMES = new Set(["충당금잔액", "적립요율(%)"]);
/** 참고 정보(차감 아님) 대분류 — 별도 섹션으로 분리. */
const INFO_ROOT = "잡수입";
/** 합계 대분류 — 강조 표시. */
const TOTAL_NAME = "합계";
/** 노출 최대 트리 레벨(level 3 세부 지표는 접음 — 대분류 위주 고지서). */
const MAX_DISPLAY_LEVEL = 2;

export interface InvoiceGroup {
  name: string;
  amount: number;
  rows: BreakdownRow[]; // level 1~2 하위 항목(숨김 항목 제외)
}

export interface Invoice {
  groups: InvoiceGroup[]; // 공용관리비·개별사용료·장기수선충당금 월부과액 등
  total: BreakdownRow | null; // 합계(강조)
  info: InvoiceGroup | null; // 잡수입(참고 — 차감 아님)
}

/** 순서 보존 리스트 → 고지서 구조. level 0 을 그룹 헤더로 삼아 하위 행을 묶는다. */
export function buildInvoice(rows: BreakdownRow[]): Invoice {
  const groups: InvoiceGroup[] = [];
  let total: BreakdownRow | null = null;
  let info: InvoiceGroup | null = null;
  let current: InvoiceGroup | null = null;

  for (const row of rows) {
    if (row.level === 0) {
      if (row.name === TOTAL_NAME) {
        total = row;
        current = null;
        continue;
      }
      const group: InvoiceGroup = { name: row.name, amount: row.amount, rows: [] };
      if (row.name === INFO_ROOT) {
        info = group;
      } else {
        groups.push(group);
      }
      current = group;
      continue;
    }
    if (!current) continue; // level 0 헤더 없이 시작된 행 방어
    if (row.level > MAX_DISPLAY_LEVEL) continue;
    if (HIDDEN_NAMES.has(row.name)) continue;
    current.rows.push(row);
  }

  return { groups, total, info };
}
