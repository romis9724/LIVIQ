/**
 * 가입 승인 순수 로직 — 명부 파일 경계 검증·거절 사유 검증·표시 포맷.
 * 렌더·네트워크와 무관한 계산만 담는다(테스트 대상). 이름 마스킹은 서버가 수행.
 */

/** 명부 엑셀 허용 확장자·최대 용량(절대규칙: 경계 입력 검증). */
export const ROSTER_ACCEPT = ".xlsx";
export const ROSTER_MAX_BYTES = 10 * 1024 * 1024; // 10MB

/**
 * 명부 파일 검증(경계 입력). 통과 시 null, 실패 시 사용자 안내 메시지.
 * ponytail: 확장자·용량만 — 실제 파싱은 서버 몫.
 */
export function validateRoster(file: { name: string; size: number }): string | null {
  if (!file.name.toLowerCase().endsWith(ROSTER_ACCEPT)) {
    return `${ROSTER_ACCEPT} 형식의 명부 파일만 올릴 수 있습니다.`;
  }
  if (file.size > ROSTER_MAX_BYTES) {
    return `파일이 너무 큽니다. 최대 ${ROSTER_MAX_BYTES / (1024 * 1024)}MB까지 가능합니다.`;
  }
  return null;
}

/** 거절 사유 유효성 — 서버가 min_length 1 을 요구하므로 공백만 있으면 거부. */
export function isValidRejectReason(reason: string): boolean {
  return reason.trim().length > 0;
}

/**
 * 세대 표기 — "101동 1002호". 동·호가 없으면(명부 미매칭 등) 남는 정보만 조합.
 * floor 는 표시에 쓰지 않는다(unit_no 가 층·호 결합 표기).
 */
export function formatUnit(buildingName: string | null, unitNo: number | null): string {
  const parts: string[] = [];
  if (buildingName) parts.push(`${buildingName}동`);
  if (unitNo !== null) parts.push(`${unitNo}호`);
  return parts.length > 0 ? parts.join(" ") : "세대 정보 없음";
}
