/**
 * 답변 진행 단계 표시 (H18-3 ① — Perplexity 계열 "무엇을 하고 있는지").
 *
 * SSE `status` 이벤트의 `stage`·`tool`(ADR-0025 §5)을 사람이 읽는 한 줄로 바꾼다.
 * 라벨을 **명사형**으로 통일한 이유: 스트리밍 중에는 뒤에 "중…"을 붙여 진행형으로 쓰고,
 * 끝난 뒤 접이식 목록에서는 그대로 "한 일"의 기록으로 읽혀야 한다 — 두 벌을 두지 않는다.
 */

import type { Stage } from "./api";

/** 도구 이름 → 명사형 라벨. 도구 목록은 ai_core/tools/*.py 가 단일 출처. */
export const TOOL_LABELS: Record<string, string> = {
  search_documents: "단지 문서 검색",
  get_fees: "관리비 내역 확인",
  get_my_inquiries: "내 민원 내역 확인",
  search_similar_inquiries: "비슷한 민원 사례 검색",
  trace_home_device_issue: "우리 집 설비 이력 추적",
  find_nearest_available_parking: "가까운 빈 주차자리 검색",
  find_in_floor_plan: "평면도 위치 검색",
  get_facilities: "시설 현황 확인",
  get_overdue_checks: "점검 일정 확인",
  search_facility_graph: "시설 관계도 탐색",
  ask_clarification: "질문 내용 확인",
};

/** 도구 없는 단계. 서버가 stage 3종만 보낸다는 계약(ADR-0025 §5)이라 폴백이 필요 없다. */
const STAGE_LABELS: Record<Stage, string> = {
  searching: "근거 검색",
  generating: "답변 작성",
  verifying: "출처 확인",
};

/** 매핑에 없는 도구(서버에 새 도구가 붙었을 때)도 화면이 깨지지 않게 일반 문구로 떨어뜨린다. */
export const UNKNOWN_TOOL_LABEL = "단지 데이터 조회";

/** 한 status 이벤트 → 표시 라벨. 도구가 있으면 도구가 이긴다(더 구체적이라). */
export function progressLabel(stage: Stage, tool: string | null): string {
  if (tool) return TOOL_LABELS[tool] ?? UNKNOWN_TOOL_LABEL;
  return STAGE_LABELS[stage] ?? UNKNOWN_TOOL_LABEL;
}

/**
 * 진행 단계 누적(불변). 같은 라벨이 연달아 오면 합친다 —
 * 도구 루프가 같은 stage 를 여러 번 보내도 "근거 검색"이 3줄 쌓이면 읽을 값이 없다.
 */
export function appendProgress(
  steps: readonly string[],
  stage: Stage,
  tool: string | null,
): string[] {
  const label = progressLabel(stage, tool);
  if (steps[steps.length - 1] === label) return [...steps];
  return [...steps, label];
}
