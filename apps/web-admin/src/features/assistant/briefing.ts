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
 * KST 날짜 키 "YYYY-MM-DD" — 탭 저장 키의 접미(H20-3, ADR-0028 결정 2 개정).
 * 날이 바뀌면 저장 키가 달라져 자연히 빈 상태가 되고, 서버도 당일 대화만 주므로
 * 새 대화 + 브리핑으로 시작한다. en-CA 로케일이 곧 ISO 날짜 표기다.
 */
export function kstDateKey(now: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(now);
}

/** 관리자 답변 CTA — 민원 집계 도구가 라우팅됐으면 민원현황으로 보낸다. */
export function isInquirySummaryAnswer(toolPath: readonly string[] | undefined): boolean {
  return toolPath?.includes("summarize_inquiries") ?? false;
}
