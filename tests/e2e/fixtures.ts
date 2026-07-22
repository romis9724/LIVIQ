// E2E 전용 고정 상수 — 시드·config·spec 공유 (docs/09 §8.2 H2-7).
// dev 시드(1111…·2222…)와 충돌하지 않도록 ee2e… 네임스페이스 UUID를 쓴다.

import path from "node:path";

// 세션 로그인 셋업(auth.setup.ts)이 저장하고 여정 프로젝트가 재사용하는 storageState 경로.
export const STORAGE_STATE = path.join(__dirname, ".auth", "session.json");

export const E2E = {
  tenantId: "ee2e0000-0000-4000-8000-000000000001",
  userId: "ee2e0000-0000-4000-8000-000000000002",
  // 시드 user.login_id = email 의 keyed HMAC(seed.ts가 pii.py와 동일하게 계산).
  // auth.setup.ts 가 아래 email/password 로 /auth/login 을 호출해 세션을 확립한다.
  // example.com — .test/.example 등 특수용도 TLD는 pydantic EmailStr(email-validator)이 거부한다.
  email: "e2e-resident@example.com",
  password: "e2e-password-liviq-1",
  buildingId: "ee2e0000-0000-4000-8000-000000000003",
  householdId: "ee2e0000-0000-4000-8000-000000000004",
  notice1Id: "ee2e0000-0000-4000-8000-000000000005",
  notice2Id: "ee2e0000-0000-4000-8000-000000000006",
  feeCurrentId: "ee2e0000-0000-4000-8000-00000000000a",
  feePrevId: "ee2e0000-0000-4000-8000-00000000000b",
  // 가입 여정용 2호 세대 — 명부 불일치 신청자가 붙는 유효 세대(조회 성공, 매칭 실패).
  household2Id: "ee2e0000-0000-4000-8000-00000000000c",
} as const;

// 시스템 테넌트 + E2E SYS_ADMIN — 가입 여정 시작점(단지 생성·소장 초대, H7-4).
// login_id = email HMAC · password_hash = E2E와 동일 상수(seed.ts) · must_change_password=false로
// 임시 비밀번호 강제 변경을 우회한다(부트스트랩 경로는 pytest 커버, ADR-0014). seed.ts가 멱등 심음.
export const SYS = {
  tenantId: "00000000-0000-0000-0000-000000000000", // app.config.SYSTEM_TENANT_ID
  userId: "ee2e0000-0000-4000-8000-0000000000f0",
  email: "sysadmin-e2e@example.com",
} as const;

// 가입 여정 단지 — SYS_ADMIN이 UI로 생성(tenantName). seed.ts·spec beforeAll이 반복 실행 전
// name LIKE 'E2E-%' 단지를 정리해 누적을 막는다(E2E 고정 단지 'E2E 단지'는 하이픈이 없어 미포함).
export const JOURNEY = {
  tenantName: "E2E-여정단지",
  managerEmail: "e2e-manager@example.com",
  staffEmail: "e2e-staff@example.com",
  applicantEmail: "e2e-applicant@example.com", // 명부 일치 주민
  mismatchEmail: "e2e-mismatch@example.com", // 명부 불일치 주민
  password: "e2e-password-liviq-1", // ≥10자(ADR-0014). 초대 수락·가입 시 UI로 설정.
  // 인증·초대 메일은 console 백엔드라 E2E가 stdout을 못 읽는다 — 원문을 아는 토큰을 pg로 직접
  // INSERT하고(seed.insertAuthToken) 브라우저로 링크를 탄다(sha256 hex만 DB 저장, auth_tokens).
  inviteToken: "e2e-invite-tok-0001",
  applicantVerifyToken: "e2e-verify-tok-0001",
  mismatchVerifyToken: "e2e-verify-tok-0002",
} as const;

// 명부 일치 가입자 — roster-e2e.xlsx 한 행과 동일해야 매칭(name_hash+birth_hash). 세대=101동 3층 301호.
export const ROSTER_PERSON = {
  name: "김입주",
  birth: "1990-05-15",
  dong: "101",
  ho: "301",
} as const;

// 명부 불일치 가입자 — 명부에 없는 정보. 세대는 2호(존재하는 세대라 조회는 성공, 매칭만 실패).
export const MISMATCH_PERSON = {
  name: "차없음",
  birth: "1988-08-08",
  dong: "101",
  ho: "302",
} as const;

/** approvals.py mask_name 과 동일 — 2자: 첫+*, 3자+: 첫+*+끝. */
export function maskName(name: string): string {
  if (name.length <= 1) return "*";
  if (name.length === 2) return `${name[0]}*`;
  return `${name[0]}*${name[name.length - 1]}`;
}

export const PORTS = {
  api: 8000,
  resident: 3000,
  admin: 3001,
} as const;

export const BUILDING_NAME = "101";
export const FLOOR = 3;
export const UNIT_NO = 301;

// 시드된 공지 — 상세 진입 본문 확인에 사용.
export const NOTICE1 = {
  title: "E2E 정기 소독 안내",
  body: "이번 주 목요일 오전 10시부터 정기 소독을 실시합니다. 창문을 닫아 주세요.",
};
export const NOTICE2 = {
  title: "E2E 승강기 점검 공지",
  body: "다음 주 월요일 승강기 정기 점검이 예정되어 있습니다.",
};

/** 이번 달(YYYY-MM) — FeesView.currentMonth()과 동일 규칙. */
export function currentMonth(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** 직전 달(YYYY-MM). */
export function prevMonth(now: Date = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// 시드 관리비 합계(원). 당월 > 전월 → "전월 대비 ▲" 렌더 확인.
export const FEE_CURRENT_TOTAL = 238400;
export const FEE_PREV_TOTAL = 210000;
// H8-7: breakdown = 순서 보존 트리 리스트([{name,level,amount}]). level 0=대분류·합계.
// level 1 합 = 238400 = 공용관리비 = 합계(정합).
export interface FeeBreakdownRow {
  name: string;
  level: number;
  amount: number;
}
export const FEE_BREAKDOWN: FeeBreakdownRow[] = [
  { name: "공용관리비", level: 0, amount: 238400 },
  { name: "일반관리비", level: 1, amount: 120000 },
  { name: "청소비", level: 1, amount: 38400 },
  { name: "경비비", level: 1, amount: 50000 },
  { name: "승강기유지비", level: 1, amount: 30000 },
  { name: "합계", level: 0, amount: 238400 },
];
