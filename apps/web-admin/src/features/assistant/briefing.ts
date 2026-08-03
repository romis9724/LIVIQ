// 관리자 진입 브리핑 — 순수 로직만(테스트 대상). 발동·렌더는 AdminAssistant 가 한다.
// ADR-0028 결정 3: 빈 대화면 프론트가 고정 질의 1회를 자동 전송하고, 그 사용자 말풍선은 숨긴다.

/**
 * 브리핑 질문의 고정 꼬리 — 날짜만 앞에 갈아 끼운다(숨김 판정도 이 꼬리로 한다).
 * 기간("최근 7일")을 **선제 명시**한다: 안 주면 모델이 기간을 되물어 브리핑이 빈손으로 끝났다
 * (사내 배포 실화면 보고, H20-3). "민원 현황" 키워드는 8B 라우팅 앵커라 유지 — 문장 구조를
 * 크게 바꾸면 도구 라우팅이 무너진다(docs/09 H20-2 기각 실측).
 */
const BRIEFING_TAIL =
  "관리소장에게 간단히 인사하고, 최근 7일 민원 현황을 요약한 뒤 오늘 우선 처리해야 할 일을 알려주세요.";

/**
 * 구 꼬리(기간 없는 버전) — 숨김 판정에만 쓴다. 당일 복원본(서버·탭 저장)에 이 문구로 보낸
 * 브리핑이 남아 있을 수 있어서다. 대화는 당일치만 복원되므로 **배포 다음 날이면 제거해도 안전**.
 */
const LEGACY_BRIEFING_TAIL =
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
  const trimmed = text.trim();
  return trimmed.endsWith(BRIEFING_TAIL) || trimmed.endsWith(LEGACY_BRIEFING_TAIL);
}

/**
 * KST 날짜 키 "YYYY-MM-DD" — 탭 저장 키의 접미(H20-3, ADR-0028 결정 2 개정).
 * 날이 바뀌면 저장 키가 달라져 자연히 빈 상태가 되고, 서버도 당일 대화만 주므로
 * 새 대화 + 브리핑으로 시작한다. en-CA 로케일이 곧 ISO 날짜 표기다.
 */
export function kstDateKey(now: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(now);
}

// 관리자 답변 CTA 판정 — 근거는 **도구 이름(toolPath)** 뿐이다. 모델 자유텍스트에서
// 화면·번호를 파싱해 링크를 만들지 않는다(규칙 8). 입주민 전용 도구(빈자리·내 차 위치·
// 세대 평면도)는 RESIDENT_ROLES 게이트라 관리자에겐 애초에 라우팅되지 않으므로,
// 관리자가 실제로 받는 도구에 맞는 등가 CTA를 단다(H20-12).

/** 관리자 답변 CTA — 민원 집계 도구가 라우팅됐으면 민원현황으로 보낸다. */
export function isInquirySummaryAnswer(toolPath: readonly string[] | undefined): boolean {
  return toolPath?.includes("summarize_inquiries") ?? false;
}

/** FACILITY_ROLES 시설 도구 — ai_core tools/library.py 의 이름과 같아야 한다. */
const FACILITY_TOOLS = ["get_facilities", "get_overdue_checks", "search_facility_graph"];

/**
 * 설비 현황·점검 기한·원인 추적 답변인가 — 시설관리 화면(전체화면 3D 그래프)으로 보낸다.
 * ponytail: 딥링크 파라미터는 두지 않는다(강조할 쿼리 계약이 `/facilities` 에 없다).
 * 설비 코드 강조가 필요해지면 `/parking?spot=` 처럼 그때 additive 로 붙인다.
 */
export function isFacilityAnswer(toolPath: readonly string[] | undefined): boolean {
  return toolPath?.some((tool) => FACILITY_TOOLS.includes(tool)) ?? false;
}

/** 최근 공지 목록 답변인가 — 게시판으로 보낸다(문서 검색으로 답한 공지 '내용'은 제외). */
export function isRecentNoticesAnswer(toolPath: readonly string[] | undefined): boolean {
  return toolPath?.includes("get_recent_notices") ?? false;
}
