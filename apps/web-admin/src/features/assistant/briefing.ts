// 관리자 진입 브리핑 — 순수 로직만(테스트 대상). 발동·렌더는 AdminAssistant 가 한다.
// ADR-0028 결정 3: 빈 대화면 프론트가 고정 질의 1회를 자동 전송하고, 그 사용자 말풍선은 숨긴다.

/** 브리핑 질문의 고정 꼬리 — 날짜만 앞에 갈아 끼운다(숨김 판정도 이 꼬리로 한다). */
const BRIEFING_TAIL =
  "관리소장에게 간단히 인사하고, 현재 민원 현황을 요약한 뒤 오늘 우선 처리해야 할 일을 알려주세요.";

/**
 * 진입 브리핑 질문. 날짜를 본문에 넣는 이유는 8B 의 상대날짜 한계 보정(ADR-0028 결정 3).
 * "오늘"만 주면 모델이 학습 시점 기준으로 답한다.
 */
export function briefingPrompt(now: Date): string {
  const y = now.getFullYear();
  const m = now.getMonth() + 1;
  const d = now.getDate();
  return `오늘은 ${y}년 ${m}월 ${d}일입니다. ${BRIEFING_TAIL}`;
}

/**
 * 이 사용자 메시지가 자동 브리핑인가 — 말풍선 숨김 판정.
 * 날짜가 아니라 **꼬리**로 본다: sessionStorage 로 복원된 어제 대화도 그대로 숨겨야 한다.
 */
export function isBriefingPrompt(text: string): boolean {
  return text.trim().endsWith(BRIEFING_TAIL);
}

/**
 * 마운트 직후 브리핑을 발동할지 — **탭 저장소**에 복원될 대화가 없을 때만.
 * 훅의 messages state 로 판정하면 안 된다: 복원도 effect 라 같은 커밋에서는 아직 빈
 * 배열이고(레이스), 복원된 대화 위에 브리핑이 끼어든다. 저장소를 직접(동기) 본다.
 * null = 저장된 적 없음(새 탭·로그인), 0건 = '새 대화' 마커 후 재진입 — 둘 다 브리핑 대상.
 * "빈 대화로 전이할 때마다"가 아니다: 사용자가 '새 대화'로 비운 화면에 자동 질의가
 * 끼어드는 UX 를 막으려고 호출부는 마운트 1회 ref 가드를 함께 쓴다.
 */
export function shouldBrief(storedMessageCount: number | null): boolean {
  return storedMessageCount === null || storedMessageCount === 0;
}

/** 관리자 답변 CTA — 민원 집계 도구가 라우팅됐으면 민원현황으로 보낸다. */
export function isInquirySummaryAnswer(toolPath: readonly string[] | undefined): boolean {
  return toolPath?.includes("summarize_inquiries") ?? false;
}
