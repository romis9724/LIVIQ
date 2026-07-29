/**
 * 측정 단가 — 질의당 원가(cost_per_query_usd) 산출용 (H15-2).
 *
 * 토큰은 서버 done 이벤트의 전 turn 합산(도구 결정 turn + 최종 답변 turn)이다 — 원가는
 * 하한이 아니라 실사용 근사값이고, 추정 혼입 여부는 token_estimated로 별도 표기된다.
 *
 * 단가는 측정 시점 공식 가격표를 확인해 env로 주입한다 — 코드에 박으면 낡는다.
 *   LIVIQ_EVAL_PRICE_IN  = 입력 1M 토큰당 USD
 *   LIVIQ_EVAL_PRICE_OUT = 출력 1M 토큰당 USD
 * env가 있으면 모델(--label)을 몰라도 계산되므로 신규 모델도 그대로 잰다.
 *
 * env가 없으면 아래 표로 대체한다 — 자체 장비에서 도는 로컬 모델은 API 단가 0
 * (전력·장비 감가는 이 도구의 범위 밖). 표에 없고 env도 없으면 null = 원가 미산출.
 */

// 러너 --label → 1M 토큰당 USD. 로컬 모델(자체 장비)은 0.
const LABEL_PRICING = {
  "llama3.1-8b-awq": { inputPer1M: 0, outputPer1M: 0 },
  "llama3.1:8b": { inputPer1M: 0, outputPer1M: 0 },
};

function envPrice(env, name) {
  const raw = env[name];
  if (raw === undefined || String(raw).trim() === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`${name} 값이 0 이상의 숫자가 아님: ${raw}`);
  }
  return value;
}

/**
 * 라벨의 단가. env 주입이 표보다 우선. 알 수 없으면 null(원가 미산출).
 * 한쪽만 주입하면 나머지가 0으로 조용히 새므로 둘 다 요구한다(fail fast).
 * @returns {{ inputPer1M: number, outputPer1M: number, currency: "USD", source: "env"|"table" }|null}
 */
export function pricingFor(label, env = process.env) {
  const input = envPrice(env, "LIVIQ_EVAL_PRICE_IN");
  const output = envPrice(env, "LIVIQ_EVAL_PRICE_OUT");
  if (input !== null || output !== null) {
    if (input === null || output === null) {
      throw new Error("LIVIQ_EVAL_PRICE_IN·LIVIQ_EVAL_PRICE_OUT은 함께 지정 — 한쪽만은 원가 왜곡");
    }
    return { inputPer1M: input, outputPer1M: output, currency: "USD", source: "env" };
  }
  const table = LABEL_PRICING[label];
  return table ? { ...table, currency: "USD", source: "table" } : null;
}

/** 단가가 실제로 돈이 드는가 — 로컬 0단가는 비용 열을 출력하지 않는다(0.00 잡음 방지). */
export function isPriced(pricing) {
  return pricing !== null && (pricing.inputPer1M > 0 || pricing.outputPer1M > 0);
}

/** 토큰 → USD. 소수 6자리로 반올림(µ달러 단위). pricing이 null이면 null. */
export function costUsd(pricing, tokenIn, tokenOut) {
  if (pricing === null) return null;
  const raw = (tokenIn / 1e6) * pricing.inputPer1M + (tokenOut / 1e6) * pricing.outputPer1M;
  return Math.round(raw * 1e6) / 1e6;
}
