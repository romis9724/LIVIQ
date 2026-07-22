/**
 * 동/호수 관리 순수 로직 — 층·호 범위 검증·조합 수·미리보기. (H8-5)
 * 렌더·네트워크와 무관한 계산만 담는다(테스트 대상). 서버 계약(BULK_MAX_HOUSEHOLDS)과 일치.
 */

/** 1회 일괄 생성 상한 — 서버(app/schemas/households.py)와 동일. */
export const BULK_MAX_HOUSEHOLDS = 2000;
export const FLOOR_MIN = -10;
export const FLOOR_MAX = 200;
export const UNIT_MIN = 1;
export const UNIT_MAX = 99;

export interface RangeInput {
  floorStart: number;
  floorEnd: number;
  unitStart: number;
  unitEnd: number;
}

/**
 * 층·호 범위 검증. 통과하면 null, 아니면 사용자용 오류 메시지.
 * 정수·범위 한계·역순·상한 초과를 서버보다 먼저 잡아 왕복을 줄인다(서버가 최종 방어).
 */
export function validateRange(input: RangeInput): string | null {
  const { floorStart, floorEnd, unitStart, unitEnd } = input;
  const values = [floorStart, floorEnd, unitStart, unitEnd];
  if (values.some((v) => !Number.isInteger(v))) {
    return "층·호는 정수로 입력해 주세요.";
  }
  if (floorStart < FLOOR_MIN || floorEnd > FLOOR_MAX) {
    return `층은 ${FLOOR_MIN}~${FLOOR_MAX} 범위여야 합니다.`;
  }
  if (unitStart < UNIT_MIN || unitEnd > UNIT_MAX) {
    return `호는 ${UNIT_MIN}~${UNIT_MAX} 범위여야 합니다.`;
  }
  if (floorEnd < floorStart) {
    return "끝 층은 시작 층 이상이어야 합니다.";
  }
  if (unitEnd < unitStart) {
    return "끝 호는 시작 호 이상이어야 합니다.";
  }
  if (countCombos(input) > BULK_MAX_HOUSEHOLDS) {
    return `1회 최대 ${BULK_MAX_HOUSEHOLDS.toLocaleString()}세대까지 생성할 수 있습니다.`;
  }
  return null;
}

/** 범위가 만들 세대 수(검증 통과 여부와 무관한 순수 곱). 역순이면 0. */
export function countCombos(input: RangeInput): number {
  const floors = input.floorEnd - input.floorStart + 1;
  const units = input.unitEnd - input.unitStart + 1;
  if (floors <= 0 || units <= 0) return 0;
  return floors * units;
}

/** "N층 M호" 라벨(호는 2자리 0채움: 3층 1호 → "301호" 형태 힌트용). */
export function unitLabel(floor: number, unitNo: number): string {
  return `${floor}${String(unitNo).padStart(2, "0")}호`;
}

/** 미리보기용 상위 라벨 몇 개(층 오름차순·호 오름차순). 조합이 limit보다 많으면 잘라서 반환. */
export function previewLabels(input: RangeInput, limit = 6): string[] {
  const labels: string[] = [];
  for (let floor = input.floorStart; floor <= input.floorEnd; floor += 1) {
    for (let unit = input.unitStart; unit <= input.unitEnd; unit += 1) {
      if (labels.length >= limit) return labels;
      labels.push(unitLabel(floor, unit));
    }
  }
  return labels;
}
