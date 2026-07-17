/**
 * 관리비 화면 순수 헬퍼 — 표시 포맷·전월 대비만 담당.
 * 관리비는 엑셀 업로드가 단일 출처이며 AI·클라이언트는 계산·부과에 관여하지 않는다(규칙 5).
 * 합계·항목 금액은 서버 값을 그대로 표기하고, 여기서는 증감(차액)만 파생한다.
 */

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

/** 미리보기·현황 표의 층·호 → 표기(예: 15층 2호 → "1502"). */
export function unitLabel(_floor: number, unitNo: number): string {
  // unit_no가 완전한 호수(예: 1001호 = 10층 01호) — floor와 합성하면 "101001"로 깨진다.
  return `${unitNo}호`;
}

/** 미리보기 preview 행들에서 항목(breakdown) 컬럼 키를 순서대로 수집. */
export function breakdownColumns(rows: readonly { breakdown: Record<string, number> }[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row.breakdown)) seen.add(key);
  }
  return [...seen];
}
