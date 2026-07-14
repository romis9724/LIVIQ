/**
 * AI 계층 연결 지점 (docs/07 §AI eval).
 *
 * **env 게이트**: `LIVIQ_EVAL_API_URL`이 없으면 `not-wired` 반환 → 러너가 pending 집계.
 * CI(evals.yml)는 이 env 없이 돌아 LLM 호출 0·pending 유지(안전). 로컬·스테이징에서
 * `LIVIQ_EVAL_API_URL=http://localhost:8000`로 실행하면 실제 api /assistant/ask에
 * 질의해 측정한다.
 *
 * 관측 범위: H1이 구현한 **규칙 1(출처 인용·폴백)** 키만 SSE 결과에서 도출한다.
 *   must_cite · no_hallucination · must_fallback · no_answer_from_thin_air · tool_result_cited
 * 그 외 규칙(마스킹·격리·검수·도구 등, H2+ 기능)은 관측 키를 넣지 않아 pending으로 남는다
 * (판정 불가를 정직하게 표기 — 억지 통과 금지).
 *
 * 계약: (evalCase) => Promise<{ status: "ok"|"not-wired", [observedKey]: boolean }>
 */

const API_URL = process.env.LIVIQ_EVAL_API_URL;
// 측정용 dev 컨텍스트(seed와 일치). web api.ts 기본값과 동일.
const TENANT_ID = process.env.LIVIQ_EVAL_TENANT_ID ?? "11111111-1111-1111-1111-111111111111";
const USER_ID = process.env.LIVIQ_EVAL_USER_ID ?? "22222222-2222-2222-2222-222222222222";

export async function runAgainstAiLayer(evalCase) {
  if (!API_URL) return { status: "not-wired" };

  let result;
  try {
    result = await askAssistant(evalCase.input);
  } catch {
    // 네트워크·서버 오류는 측정 불가(pending) — fail로 오염시키지 않음
    return { status: "not-wired" };
  }

  const answered = result.done?.status === "answered";
  const fallback = result.done?.status === "fallback";
  const hasCitation = result.citations.length > 0;

  // 규칙 1 관측치. 답변이면 인용 동반(출처 강제)·환각 없음, 폴백이면 지어내지 않음.
  return {
    status: "ok",
    must_cite: answered && hasCitation,
    no_hallucination: fallback || hasCitation,
    must_fallback: fallback,
    no_answer_from_thin_air: fallback,
    tool_result_cited: answered && hasCitation,
  };
}

async function askAssistant(question) {
  const response = await fetch(`${API_URL}/assistant/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Dev-Tenant-Id": TENANT_ID,
      "X-Dev-User-Id": USER_ID,
    },
    body: JSON.stringify({ question }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`assistant ${response.status}`);
  }

  const citations = [];
  let done = null;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done: streamDone, value } = await reader.read();
    if (streamDone) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.replace(/\r\n/g, "\n").split("\n\n");
    buffer = parts.pop() ?? "";
    for (const block of parts) {
      let event = "message";
      const dataLines = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) continue;
      const data = JSON.parse(dataLines.join("\n"));
      if (event === "citation") citations.push(data);
      else if (event === "done") done = data;
    }
  }
  return { citations, done };
}
