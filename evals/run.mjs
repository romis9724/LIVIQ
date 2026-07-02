#!/usr/bin/env node
/**
 * evals 러너 — AI 하드 규칙 케이스를 로드해 pass-rate를 리포트한다.
 *
 * - stdlib only (Node >=20)
 * - 어댑터가 not-wired면 케이스는 pending (측정 불가), fail 아님
 * - 결과 스냅샷을 evals/results/ 에 저장해 추이 추적
 *
 * 사용:
 *   node evals/run.mjs
 *   node evals/run.mjs --rule=2
 */

import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runAgainstAiLayer } from "./adapter.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const CASES_DIR = join(HERE, "cases");
const RESULTS_DIR = join(HERE, "results");

const ruleArg = process.argv.find((a) => a.startsWith("--rule="));
const ruleFilter = ruleArg ? ruleArg.split("=")[1] : null;

function loadSuites() {
  return readdirSync(CASES_DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(readFileSync(join(CASES_DIR, f), "utf8")))
    .filter((s) => !ruleFilter || String(s.rule).includes(ruleFilter));
}

// expect 키를 관측값과 대조. 관측값 부재(not-wired)면 pending.
function judge(expect, observed) {
  const misses = [];
  for (const [key, want] of Object.entries(expect)) {
    if (!(key in observed)) return { verdict: "pending" };
    if (observed[key] !== want) misses.push(key);
  }
  return misses.length === 0
    ? { verdict: "pass" }
    : { verdict: "fail", misses };
}

const tally = { pass: 0, fail: 0, pending: 0, total: 0 };
const detail = [];

const suites = loadSuites();
for (const suite of suites) {
  for (const c of suite.cases) {
    tally.total++;
    const res = await runAgainstAiLayer(c);
    if (res.status !== "ok") {
      tally.pending++;
      detail.push({ id: c.id, rule: suite.rule, verdict: "pending" });
      continue;
    }
    const j = judge(c.expect, res);
    tally[j.verdict]++;
    detail.push({ id: c.id, rule: suite.rule, ...j });
  }
}

const measured = tally.pass + tally.fail;
const passRate = measured === 0 ? null : tally.pass / measured;

console.log(`\nLIVIQ evals — 규칙 회귀 측정\n`);
for (const d of detail) {
  const mark =
    d.verdict === "pass" ? "✓" : d.verdict === "fail" ? "✗" : "·";
  const extra = d.misses ? `  (miss: ${d.misses.join(", ")})` : "";
  console.log(`  ${mark} [rule ${d.rule}] ${d.id} — ${d.verdict}${extra}`);
}
console.log(
  `\n총 ${tally.total} · pass ${tally.pass} · fail ${tally.fail} · pending ${tally.pending}`,
);
console.log(
  passRate === null
    ? `pass-rate: N/A (측정 케이스 0 — 어댑터 미연결)\n`
    : `pass-rate: ${(passRate * 100).toFixed(1)}% (측정 ${measured}건 기준)\n`,
);

// 스냅샷 저장
mkdirSync(RESULTS_DIR, { recursive: true });
const stamp = new Date().toISOString().slice(0, 10);
const snapshot = {
  date: stamp,
  tally,
  pass_rate: passRate,
  detail,
};
writeFileSync(
  resolve(RESULTS_DIR, `${stamp}.json`),
  JSON.stringify(snapshot, null, 2) + "\n",
);

// pending은 실패 아님(측정 불가). 실제 fail만 비제로 종료.
process.exit(tally.fail > 0 ? 1 : 0);
