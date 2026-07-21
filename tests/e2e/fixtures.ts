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
  conversationId: "ee2e0000-0000-4000-8000-000000000007",
  userMessageId: "ee2e0000-0000-4000-8000-000000000008",
  assistantMessageId: "ee2e0000-0000-4000-8000-000000000009",
  feeCurrentId: "ee2e0000-0000-4000-8000-00000000000a",
  feePrevId: "ee2e0000-0000-4000-8000-00000000000b",
  // 가입 여정(H6-4)용 2호 세대 — 명부 불일치 신청자가 붙는 유효 세대(조회 성공, 매칭 실패).
  household2Id: "ee2e0000-0000-4000-8000-00000000000c",
  // 신규 가입자 sub — mock IdP가 mock_sub 쿠키로 이 값을 발급(신원=신규 로그인).
  signupSub: "e2e-google-sub-signup",
  mismatchSub: "e2e-google-sub-mismatch",
} as const;

// 클라이언트가 하드코딩한 데모 초대코드(logic.ts VALID_INVITE_CODE). E2E 단지가 이 코드로 매핑된다.
export const INVITE_CODE = "LIVIQ1";

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

// 시드된 검수 큐 항목(needs_review).
export const REVIEW = {
  question: "E2E 검수 큐 테스트 질문입니다.",
  answer: "E2E 검수 대기 답변 — 신뢰도가 낮아 사후 검수가 필요합니다.",
  confidence: 0.35,
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
export const FEE_BREAKDOWN: Record<string, number> = {
  일반관리비: 120000,
  청소비: 38400,
  경비비: 50000,
  승강기유지비: 30000,
};
