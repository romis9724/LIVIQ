/**
 * AI 계층 연결 지점.
 *
 * apps/api · packages/ai-core 도입 후 이 함수를 실제 AI 파이프라인에 wiring한다.
 * 지금은 미구현 → { status: "not-wired" } 반환. 러너가 이를 pending으로 집계.
 *
 * 계약: (evalCase) => Promise<{
 *   status: "ok" | "not-wired",
 *   // status === "ok"일 때 판정에 필요한 관측값. 예:
 *   //   cited, fallback, piiMaskedBeforeLlm, llmCallBlocked,
 *   //   recalculatedFee, autoSent, routedToReviewQueue ...
 * }>
 */
export async function runAgainstAiLayer(_evalCase) {
  return { status: "not-wired" };
}
