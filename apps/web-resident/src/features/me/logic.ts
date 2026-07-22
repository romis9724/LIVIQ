// 나(프로필) 순수 로직 — /me 응답을 표시용 라벨로 변환. 서버가 주는 필드만 사용.

/** 역할 코드(대문자) → 한국어 라벨. */
const ROLE_LABEL: Record<string, string> = {
  RESIDENT: "입주민",
  MANAGER: "관리소장",
  STAFF: "관리사무소 직원",
};

/** 대표 역할 라벨(첫 역할). 매핑 없으면 원문, 역할 없으면 "회원". */
export function roleLabel(roles: readonly string[]): string {
  const primary = roles[0];
  if (!primary) return "회원";
  return ROLE_LABEL[primary] ?? primary;
}

/** 계정 상태 코드 → 한국어 라벨. 매핑 없으면 원문. */
const STATUS_LABEL: Record<string, string> = {
  active: "활성 계정",
  pending: "승인 대기 중",
  rejected: "승인 반려됨",
  inactive: "비활성 계정",
};

export function accountStatusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** YYYY-MM → "YYYY년 M월"(관리비 요약 라벨, 선행 0 제거). */
export function feePeriodLabel(period: string): string {
  const [year, month] = period.split("-");
  return `${year}년 ${Number(month)}월`;
}
