/**
 * 온보딩 순수 로직 — 가입 게이트 판정·서버 페이로드 변환. UI·네트워크 의존 없음(테스트 용이).
 * 실제 검증은 서버에서 재수행한다(프론트 판정은 보조).
 */

import type { AppNotification, Me, ProfilePayload } from "@/lib/api";

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

/** 계정 상태 → PendingView 카드 분기. onboarding=미제출, unknown=예상 밖 상태(방어적). */
export type AccountView = "pending" | "rejected" | "active" | "inactive" | "onboarding" | "unknown";

export function accountView(me: Pick<Me, "status">): AccountView {
  switch (me.status) {
    // registered=가입 완료·프로필 미제출 → 온보딩 필요(자체 인증, ADR-0014 · kind 폐기).
    case "registered":
      return "onboarding";
    case "pending":
    case "rejected":
    case "active":
    case "inactive":
      return me.status;
    default:
      return "unknown";
  }
}

/**
 * 루트(/) 진입 시 상태별 목적지. OAuth 콜백이 / 로 복귀할 때 상태에 맞는 화면으로 보낸다.
 * 401(미로그인)은 apiFetch 가 /login 으로 유도하므로 여기 도달하지 않는다.
 * pending·rejected·inactive·unknown 은 계정 상태 화면(/pending)이 각 상태를 안내한다.
 */
export function rootDestination(me: Pick<Me, "status">): string {
  const view = accountView(me);
  if (view === "active") return "/home";
  if (view === "onboarding") return "/onboarding";
  return "/pending";
}

/**
 * 반려 사유 추출 — /me 는 사유를 주지 않으므로 인앱 알림에서 가져온다.
 * approvals.reject 는 type="approval" + body=사유 알림을 남긴다(승인 알림은 body 없음).
 * 가장 최근 사유를 반환하고, 없으면 null.
 */
export function rejectionReasonFrom(notifications: readonly AppNotification[]): string | null {
  const rejections = notifications
    .filter((n) => n.type === "approval" && n.body)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  return rejections[0]?.body ?? null;
}

/** 가입 폼 입력값(camelCase, UI 상태). 동·호는 select 문자열. */
export interface SignupFormValues {
  inviteCode: string;
  name: string;
  birthDate: string; // YYYY-MM-DD
  dong: string; // 동(건물명) — 예: "101"
  ho: string; // 호 — 예: "1002" (층·호 결합 표기)
  privacyConsent: boolean;
  alertsConsent: boolean;
}

/**
 * 폼 입력 → 서버 계약(ProfilePayload) 변환. 층은 호수 상위 자리에서 파생한다.
 * 예: "1002호" → unit_no=1002, floor=10 · "301호" → unit_no=301, floor=3.
 */
export function buildProfilePayload(values: SignupFormValues): ProfilePayload {
  const unitNo = Number.parseInt(values.ho, 10);
  return {
    invite_code: values.inviteCode.trim(),
    consents: [
      { purpose: "privacy_required", granted: values.privacyConsent },
      { purpose: "alerts", granted: values.alertsConsent },
    ],
    name: values.name.trim(),
    birth_date: values.birthDate,
    building_name: values.dong,
    floor: Math.floor(unitNo / 100),
    unit_no: unitNo,
  };
}
