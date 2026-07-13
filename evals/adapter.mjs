/**
 * AI 계층 연결 지점.
 *
 * apps/api · packages/ai-core 도입 후 이 함수를 실제 AI 파이프라인에 wiring한다.
 * 지금은 미구현 → { status: "not-wired" } 반환. 러너가 이를 pending으로 집계.
 *
 * 계약: (evalCase) => Promise<{
 *   status: "ok" | "not-wired",
 *   // status === "ok"일 때 판정에 필요한 관측값(전부 boolean, snake_case).
 *   // 케이스 expect 키와 정확히 일치해야 하며, 여기에 계약을 한 곳에 모은다:
 *   //   규칙1 인용:  must_cite, no_hallucination, must_fallback,
 *   //               no_answer_from_thin_air, tool_result_cited
 *   //   규칙2 PII:   pii_masked_before_llm, no_raw_pii_in_prompt,
 *   //               llm_call_blocked, fallback_triggered
 *   //   규칙3 격리:  cross_tenant_data_leaked, cache_scope_respected,
 *   //               cross_household_data_blocked
 *   //   규칙4 인가:  unauthorized_query_rejected
 *   //   규칙5 관리비: no_recalculation, explains_erp_value_only
 *   //   규칙6 검수:  draft_only, no_auto_send, routed_to_review_queue
 *   //   규칙8 도구:  write_tool_invoked, step_cap_respected, guides_to_ui
 * }>
 */
export async function runAgainstAiLayer(_evalCase) {
  return { status: "not-wired" };
}
