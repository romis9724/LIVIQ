#!/usr/bin/env node
/**
 * rag500 — quality-cases-500을 실제 api(/assistant/ask)에 투입해 자동 채점하는 측정 도구.
 * H15-2(성능·품질 분석 보고서)의 데이터 수집기 — 백엔드(모델)별 품질·지연을 같은 케이스셋으로 잰다.
 *
 * 사용:
 *   LIVIQ_EVAL_API_URL=http://localhost:8000 node evals/rag500.mjs --label=ollama-llama31
 *   … --set=critical|full|all        # execution_set 라벨 필터 (기본 smoke)
 *   … --case=QA-0001,QA-0401         # 특정 케이스만
 *   … --limit=5                      # 앞 N건만
 *   … --auth=session                 # 케이스 계정으로 /auth/login 세션(역할 민감 케이스 권장)
 *   LIVIQ_EVAL_PRICE_IN=0.15 LIVIQ_EVAL_PRICE_OUT=0.60 …   # 1M 토큰당 USD → 질의당 원가 집계
 *
 * 게이트: `LIVIQ_EVAL_API_URL` 미설정 시 실행 거부(adapter.mjs와 같은 fail-safe — CI에서 안 돎).
 * 결과: evals/results/rag500/rag500-<timestamp>-<label>.json (run.mjs --trend 스냅샷과 분리).
 *
 * 측정 한계(결과 meta에도 기록):
 *   - `--auth=dev`(기본)의 dev 헤더는 역할이 DEV_ROLES 고정(deps.py) — 케이스 role 컬럼을
 *     재현하지 못한다. 역할 차단·인가 케이스는 `--auth=session`으로 실제 역할을 태운다.
 *   - 서버는 conversation_id로 대화를 묶기만 하고 이전 턴을 LLM에 넣지 않는다(orchestrator
 *     answer_question은 질문 1건만 받음) → 다중 턴은 "같은 대화의 독립 질의" 측정이다.
 *   - 답변 캐시(cache:ans:*)는 백엔드별 키라 백엔드 간 오염은 없지만, 같은 백엔드 재실행은
 *     캐시 재생으로 지연이 왜곡된다 — 지연을 다시 재려면 Redis에서 키를 비운다(캐시 히트는
 *     LLM 호출이 없어 토큰 0으로 기록되므로 원가도 같이 왜곡된다).
 *   - 토큰은 서버 done 이벤트가 준 값 = 질의 1건의 **전 turn 합산**(도구 결정 turn + 최종
 *     답변 turn, H15-2). 결정 turn이 입력 토큰의 대부분이라 예전처럼 최종 turn만 세면 원가가
 *     3분의 1 수준 하한이 된다. 단, 최종 답변 turn은 스트리밍이라 프로바이더 usage가 없어
 *     추정치가 섞인다 → token_estimated=true면 원가는 참고값(결과 meta·콘솔에 경고).
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { fixtureUuid, loadCases, loadManifest, loadUsers, turnsOf } from "./rag500-cases.mjs";
import { isPriced, pricingFor } from "./rag500-pricing.mjs";
import { aggregate, scoreCase } from "./rag500-score.mjs";
import { postSse } from "./sse.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const RESULTS_DIR = join(HERE, "results", "rag500");
const API_URL = process.env.LIVIQ_EVAL_API_URL;
// 시드 계정 공통 비밀번호(seed_rag_validation.py EVAL_PASSWORD) — 로컬 합성 계정 전용.
const EVAL_PASSWORD = process.env.LIVIQ_EVAL_PASSWORD ?? "liviq-eval-1234!";
// 사용자 분당 질의 상한(RATE_LIMIT_USER_PER_MIN 기본 10) 초과 시 냉각 후 1회 재시도.
const RATE_LIMIT_COOLDOWN_MS = 61_000;

const argOf = (name, fallback = null) => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : fallback;
};

const label = argOf("label");
if (!API_URL) {
  console.error("LIVIQ_EVAL_API_URL 미설정 — 실제 api 없이는 측정 불가(실행 거부).");
  process.exit(2);
}
if (!label) {
  console.error("--label=<backend> 필수 — 백엔드별 결과를 구분할 수 없음. 예: --label=ollama-llama31");
  process.exit(2);
}

const set = argOf("set", "smoke");
const caseIds = (argOf("case") ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const limitArg = argOf("limit");
const limit = limitArg === null ? null : Number(limitArg);
if (limit !== null && !Number.isInteger(limit)) {
  console.error(`--limit 값이 정수가 아님: ${limitArg}`);
  process.exit(2);
}
const auth = argOf("auth", "dev");
if (auth !== "dev" && auth !== "session") {
  console.error(`--auth 값은 dev|session — 받은 값: ${auth}`);
  process.exit(2);
}

const docs = loadManifest();
const users = auth === "session" ? loadUsers() : {};
// 세션 쿠키는 계정당 1회만 발급(로그인 분당 상한 5회) — 이후 케이스는 재사용.
const sessionCookies = new Map();
const cases = loadCases({ set, caseIds, limit });
if (cases.length === 0) {
  console.error(`대상 케이스 0건 — set=${set} case=${caseIds.join(",") || "-"} 필터 확인.`);
  process.exit(2);
}

console.log(`\nrag500 — ${cases.length}건 (set=${set}) · backend=${label} · api=${API_URL}\n`);

const results = [];
const errors = [];
for (const [index, row] of cases.entries()) {
  const prefix = `  [${index + 1}/${cases.length}] ${row.case_id}`;
  try {
    const turns = await askTurns(row);
    const scored = scoreCase(row, turns, docs);
    results.push(scored);
    const mark = scored.verdict === "pass" ? "✓" : "✗";
    const judge = scored.needs_judge ? " (검수)" : "";
    console.log(
      `${prefix} ${mark} ${scored.actual.status ?? "-"} · 인용 ${fmtCheck(scored.checks.citation_hit)}` +
        ` · 폴백 ${fmtCheck(scored.checks.fallback_ok)} · ${scored.latency.total_ms}ms${judge}`,
    );
  } catch (error) {
    errors.push({ case_id: row.case_id, category: row.category, error: String(error.message ?? error) });
    console.log(`${prefix} ! 측정 실패 — ${error.message ?? error}`);
  }
}

/** 케이스의 턴을 같은 대화(conversation_id)로 순차 호출. */
async function askTurns(row) {
  const headers = auth === "session" ? await sessionHeaders(row) : devHeaders(row);
  const turns = [];
  let conversationId = null;
  for (const question of turnsOf(row)) {
    const body = conversationId ? { question, conversation_id: conversationId } : { question };
    const result = await askWithCooldown(body, headers);
    turns.push(result);
    conversationId = result.done?.conversation_id ?? conversationId;
  }
  if (turns.length === 0) throw new Error("턴 없음 — turn_1 비어 있음");
  return turns;
}

/** 429(분당 상한)면 냉각 후 1회 재시도 — 빠른 백엔드에서 케이스가 유실되지 않게. */
async function askWithCooldown(body, headers) {
  try {
    return await postSse(`${API_URL}/assistant/ask`, body, headers);
  } catch (error) {
    if (error.status !== 429) throw error;
    console.log(`       429 — ${RATE_LIMIT_COOLDOWN_MS / 1000}초 대기 후 1회 재시도(분당 상한)`);
    await new Promise((done) => setTimeout(done, RATE_LIMIT_COOLDOWN_MS));
    return postSse(`${API_URL}/assistant/ask`, body, headers);
  }
}

function devHeaders(row) {
  return {
    // env 강제(adapter.mjs와 같은 이름)는 fixture 미시드 상태의 스모크용 — 없으면 ID 규약대로.
    "X-Dev-Tenant-Id": process.env.LIVIQ_EVAL_TENANT_ID ?? fixtureUuid(row.tenant_id),
    "X-Dev-User-Id": process.env.LIVIQ_EVAL_USER_ID ?? fixtureUuid(row.user_id),
    "Content-Type": "application/json",
  };
}

/** 케이스 계정으로 로그인한 세션 쿠키 헤더 — 실제 역할·테넌트가 서버에서 결정된다. */
async function sessionHeaders(row) {
  const user = users[row.user_id];
  if (!user) throw new Error(`seed/users.json에 ${row.user_id} 없음 — 세션 로그인 불가`);
  if (!sessionCookies.has(user.email)) {
    sessionCookies.set(user.email, await login(user.email));
  }
  return {
    Cookie: `liviq_session=${sessionCookies.get(user.email)}`,
    "Content-Type": "application/json",
  };
}

async function login(email) {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: EVAL_PASSWORD }),
  });
  if (!response.ok) {
    // 422는 대개 이메일 도메인 문제 — LoginIn.EmailStr이 .invalid/.test 같은 예약 도메인을 거절한다.
    const hint = response.status === 422 ? " (예약 도메인 거절 — 시드 이메일 도메인 확인)" : "";
    throw new Error(`/auth/login ${response.status} (${email})${hint} — 시드·비밀번호 확인`);
  }
  const cookie = (response.headers.getSetCookie?.() ?? [])
    .map((raw) => /(?:^|;\s*)liviq_session=([^;]+)/.exec(raw)?.[1])
    .find(Boolean);
  if (!cookie) throw new Error(`세션 쿠키 없음 — /auth/login 응답 (${email})`);
  return cookie;
}

function fmtCheck(value) {
  return value === null ? "-" : value ? "o" : "x";
}

function pct(value) {
  return value === null ? "     -" : `${(value * 100).toFixed(1).padStart(5)}%`;
}

function usd(value, digits) {
  return value === null || value === undefined ? "-" : value.toFixed(digits);
}

/** 한글은 2칸으로 세어 표 정렬 — 콘솔 표가 카테고리명 때문에 어긋나지 않게. */
function padDisplay(text, width) {
  let out = "";
  let used = 0;
  for (const ch of text) {
    const size = /[ᄀ-ᅟ⺀-꓏가-힣豈-﫿＀-｠]/.test(ch)
      ? 2
      : 1;
    if (used + size > width) break;
    out += ch;
    used += size;
  }
  return out + " ".repeat(width - used);
}

// ── 리포트 ───────────────────────────────────────────────────────────────────

const pricing = pricingFor(label);
const costOn = isPriced(pricing);
const summary = aggregate(results, errors, pricing);
const estimatedCases = summary.overall?.token_estimated_cases ?? 0;
const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const snapshot = {
  label,
  set,
  case_ids: caseIds,
  limit,
  api_url: API_URL,
  ran_at: new Date().toISOString(),
  auth,
  meta: {
    auth:
      auth === "session"
        ? "세션 로그인(/auth/login) — 케이스 계정의 실제 역할·테넌트로 호출"
        : "dev headers (X-Dev-*) — 역할은 DEV_ROLES 고정, 케이스 role 컬럼 미반영",
    multi_turn: "conversation_id 순차 호출 — 서버가 이전 턴을 LLM에 넣지 않음(독립 질의)",
    id_convention: "uuid5(NAMESPACE_URL, 'liviq-rag-validation:' + fixtureId), 문서 -V1은 -V2 별칭",
    citation_scoring: "문서 단위(document_id) — 조항·revision은 미채점(expected.citations_raw 보존)",
    token_usage:
      "전 turn 합산(도구 결정 turn + 최종 답변 turn) — " +
      (estimatedCases === 0
        ? "전 건 프로바이더 실측"
        : `추정 혼입 ${estimatedCases}/${summary.overall?.n ?? 0}건(최종 답변 turn은 스트리밍이라 usage 미제공 → 추정치), 원가는 참고값`),
  },
  pricing, // 사용한 단가(null=원가 미산출). env 주입값이면 source=env.
  summary,
  errors,
  cases: results,
};
mkdirSync(RESULTS_DIR, { recursive: true });
const outPath = join(RESULTS_DIR, `rag500-${stamp}-${label}.json`);
writeFileSync(outPath, JSON.stringify(snapshot, null, 2) + "\n");

// 토큰은 전 turn 합산 실측(추정 혼입은 아래 ⚠로 별도 표기).
// 비용 열은 단가가 주입된 경우만(로컬 0단가에서 0.00 열이 지저분해지지 않게).
const header =
  `  ${padDisplay("카테고리", 24)}  n   pass  인용hit  폴백정확  hardfail  검수  p50ms   p95ms   토큰in  토큰out` +
  (costOn ? "    원가USD  질의당USD" : "");
console.log(`\n${header}\n  ${"-".repeat(costOn ? 110 : 88)}`);
const overallRow = summary.overall ? [{ ...summary.overall, key: "전체" }] : [];
for (const b of [...summary.by_category, ...overallRow]) {
  console.log(
    `  ${padDisplay(b.key, 26)}${String(b.n).padStart(3)} ${String(b.pass).padStart(5)}` +
      `  ${pct(b.citation_hit_rate)}   ${pct(b.fallback_accuracy)}  ${String(b.hard_fail).padStart(7)}` +
      ` ${String(b.needs_judge).padStart(5)} ${String(b.total_p50_ms ?? "-").padStart(6)} ${String(b.total_p95_ms ?? "-").padStart(7)}` +
      ` ${String(b.token_input_sum).padStart(8)} ${String(b.token_output_sum).padStart(7)}` +
      (costOn
        ? ` ${usd(b.cost_usd, 6).padStart(10)} ${usd(b.cost_per_query_usd, 6).padStart(10)}`
        : ""),
  );
}
console.log(
  `\nTTFT p50 ${summary.overall?.ttft_p50_ms ?? "-"}ms · p95 ${summary.overall?.ttft_p95_ms ?? "-"}ms` +
    ` · 측정 실패 ${errors.length}건`,
);
if (costOn) {
  console.log(
    `단가 ${pricing.source} — 입력 $${pricing.inputPer1M}/1M · 출력 $${pricing.outputPer1M}/1M` +
      ` → 질의당 $${usd(summary.overall?.cost_per_query_usd, 6)}`,
  );
}
if (estimatedCases > 0) {
  console.log(
    `⚠ 추정 혼입 ${estimatedCases}/${summary.overall?.n ?? 0}건 — 최종 답변 turn은 스트리밍이라` +
      " usage 미제공(추정치). 결정 turn은 실측이므로 원가는 근사값이다",
  );
}
console.log(`결과: ${outPath}\n`);

// 채점 실패는 측정값이지 러너 오류가 아니다 — 호출 자체가 전부 실패한 경우만 비제로 종료.
process.exit(results.length === 0 ? 1 : 0);
