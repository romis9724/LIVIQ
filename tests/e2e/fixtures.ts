// E2E 전용 고정 상수 — 시드·config·spec 공유 (docs/09 §8.2 H2-7).
// dev 시드(1111…·2222…)와 충돌하지 않도록 ee2e… 네임스페이스 UUID를 쓴다.

export const E2E = {
  tenantId: "ee2e0000-0000-4000-8000-000000000001",
  userId: "ee2e0000-0000-4000-8000-000000000002",
  buildingId: "ee2e0000-0000-4000-8000-000000000003",
  householdId: "ee2e0000-0000-4000-8000-000000000004",
  notice1Id: "ee2e0000-0000-4000-8000-000000000005",
  notice2Id: "ee2e0000-0000-4000-8000-000000000006",
  conversationId: "ee2e0000-0000-4000-8000-000000000007",
  userMessageId: "ee2e0000-0000-4000-8000-000000000008",
  assistantMessageId: "ee2e0000-0000-4000-8000-000000000009",
  feeCurrentId: "ee2e0000-0000-4000-8000-00000000000a",
  feePrevId: "ee2e0000-0000-4000-8000-00000000000b",
} as const;

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
