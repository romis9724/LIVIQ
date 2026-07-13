/**
 * 온보딩 순수 로직 — 가입 게이트 판정. UI·네트워크 의존 없음(테스트 용이).
 * 실제 검증은 서버에서 재수행한다(프론트 판정은 보조). 여기 값은 데모 목업용.
 */

/** 데모 유효 초대코드. 실서비스에서는 서버가 단지별 코드를 검증한다. */
export const VALID_INVITE_CODE = "LIVIQ1";

/** 만 나이 하한. FR-ONB: 만 14세 미만 가입 차단. */
export const MIN_SIGNUP_AGE = 14;

/** 초대코드 검증(데모). 공백 제거·대문자 정규화 후 비교. */
export function isValidInviteCode(code: string): boolean {
  return code.trim().toUpperCase() === VALID_INVITE_CODE;
}

/** ISO 날짜 문자열(YYYY-MM-DD)을 타임존 영향 없이 파싱. 형식 불일치는 null. */
function parseISODate(iso: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.trim());
  if (!match) return null;
  const [, year, month, day] = match;
  return { year: Number(year), month: Number(month), day: Number(day) };
}

/**
 * 생년월일 기준 만 나이(full years). 형식이 잘못되면 null.
 * new Date() 파싱은 타임존 경계 버그가 있어 문자열을 직접 비교한다.
 */
export function fullAge(birthISO: string, today: Date = new Date()): number | null {
  const birth = parseISODate(birthISO);
  if (!birth) return null;

  const todayYear = today.getFullYear();
  const todayMonth = today.getMonth() + 1; // 1-based
  const todayDay = today.getDate();

  let age = todayYear - birth.year;
  const hasHadBirthday =
    todayMonth > birth.month || (todayMonth === birth.month && todayDay >= birth.day);
  if (!hasHadBirthday) age -= 1;

  return age;
}

/** 만 14세 미만 여부. 미입력·형식오류는 false(필수 입력 검증은 별도). */
export function isUnderMinAge(birthISO: string, today?: Date): boolean {
  const age = fullAge(birthISO, today);
  return age !== null && age < MIN_SIGNUP_AGE;
}

/**
 * 한국어 성명 마스킹 — 첫·끝 글자만 노출, 가운데는 *. 절대규칙 2(개인정보) 표시 보조.
 * 홍길동 → 홍*동 · 남궁민수 → 남**수 · 김수 → 김* · 홍 → 홍
 */
export function maskKoreanName(name: string): string {
  const trimmed = name.trim();
  if (trimmed.length <= 1) return trimmed;
  if (trimmed.length === 2) return `${trimmed[0]}*`;
  const first = trimmed[0];
  const last = trimmed[trimmed.length - 1];
  return `${first}${"*".repeat(trimmed.length - 2)}${last}`;
}
