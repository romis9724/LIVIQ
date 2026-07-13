/**
 * 가입 승인 순수 로직 — 명부 diff 요약·PII 마스킹·가입 상태 전이.
 * 렌더·타이머와 무관한 계산만 담는다(테스트 대상).
 */

/** 명부 엑셀 허용 확장자·최대 용량(절대규칙: 경계 입력 검증). */
export const ROSTER_ACCEPT = ".xlsx";
export const ROSTER_MAX_BYTES = 10 * 1024 * 1024; // 10MB

/** 새 명부에서 사라진(전출 후보) 세대. */
export interface MoveOutCandidate {
  id: string;
  unit: string; // 동호수
  name: string; // 원본 성함 — 표시 시 maskName 적용
}

/**
 * 명부 diff 병합 결과.
 * - newRegistered: 새로 사전등록(pre_registered)된 세대 수
 * - matchedKept: 기존 매칭 유지(불변) 세대 수
 * - moveOutCandidates: 새 명부에서 빠져 전출 후보로 표시된 세대
 */
export interface RosterDiffResult {
  newRegistered: number;
  matchedKept: number;
  moveOutCandidates: readonly MoveOutCandidate[];
}

export interface DiffSummary {
  newRegistered: number;
  matchedKept: number;
  moveOutCandidates: number;
}

/** 배지 3종에 쓰는 요약 수치. 전출 후보는 목록 길이에서 파생. */
export function summarizeDiff(diff: RosterDiffResult): DiffSummary {
  return {
    newRegistered: diff.newRegistered,
    matchedKept: diff.matchedKept,
    moveOutCandidates: diff.moveOutCandidates.length,
  };
}

/** 전출 후보 비활성화 — 해당 세대를 목록에서 제거한 새 배열 반환(불변). */
export function deactivateCandidate(
  candidates: readonly MoveOutCandidate[],
  id: string,
): MoveOutCandidate[] {
  return candidates.filter((c) => c.id !== id);
}

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

export type SignupStatus = "pending" | "approved" | "rejected";

export interface PendingSignup {
  id: string;
  name: string; // 원본 성함 — 표시 시 maskName
  birth: string; // YYYY-MM-DD — 표시 시 maskBirth
  unit: string; // 동호수
  appliedAt: string; // 신청일
  policyVersion: string; // 동의 약관 버전
  rosterMatch: boolean; // 명부 자동 대조 결과
  status: SignupStatus;
}

/** 가입 신청 상태 전이 — 해당 id의 status만 바꾼 새 배열 반환(불변). */
export function decideSignup(
  items: readonly PendingSignup[],
  id: string,
  status: SignupStatus,
): PendingSignup[] {
  return items.map((item) => (item.id === id ? { ...item, status } : item));
}

/** 아직 처리되지 않은(대기) 신청 수. 0이면 빈 상태로 전환. */
export function pendingCount(items: readonly PendingSignup[]): number {
  return items.filter((item) => item.status === "pending").length;
}

/**
 * 성함 마스킹(docs/06 화면 노출 규칙). 홍길동 → 홍*동, 김수 → 김*.
 * 가운데 글자를 별표로 가리고 첫·끝 글자는 남긴다.
 */
export function maskName(name: string): string {
  const chars = [...name];
  if (chars.length <= 1) return name;
  if (chars.length === 2) return `${chars[0]}*`;
  return `${chars[0]}${"*".repeat(chars.length - 2)}${chars[chars.length - 1]}`;
}

/** 생년월일 마스킹 — 앞 2자리(세기)만 남기고 나머지 숫자를 가린다. 1985-03-12 → 19**-**-**. */
export function maskBirth(birth: string): string {
  return birth.slice(0, 2) + birth.slice(2).replace(/\d/g, "*");
}
