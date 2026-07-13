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
 *   node evals/run.mjs --trend      # 스냅샷 추이만 출력
 */

import {
  readFileSync,
  readdirSync,
  writeFileSync,
  appendFileSync,
  mkdirSync,
  existsSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runAgainstAiLayer } from "./adapter.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const CASES_DIR = join(HERE, "cases");
const RESULTS_DIR = join(HERE, "results");

const ruleArg = process.argv.find((a) => a.startsWith("--rule="));
const ruleFilter = ruleArg ? ruleArg.split("=")[1] : null;

// --trend: 저장된 스냅샷을 날짜순으로 읽어 pass-rate(측정 0이면 pending) 추이 출력.
if (process.argv.includes("--trend")) {
  printTrend();
  process.exit(0);
}

function printTrend() {
  console.log(`\nLIVIQ evals — pass-rate 추이\n`);
  if (!existsSync(RESULTS_DIR)) {
    console.log(`  스냅샷 없음 — 먼저 node evals/run.mjs 실행\n`);
    return;
  }
  const snaps = readdirSync(RESULTS_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => JSON.parse(readFileSync(join(RESULTS_DIR, f), "utf8")));
  if (snaps.length === 0) {
    console.log(`  스냅샷 없음 — 먼저 node evals/run.mjs 실행\n`);
    return;
  }
  console.log(`  날짜         pass  fail  pending  pass-rate`);
  for (const s of snaps) {
    const t = s.tally;
    const rate =
      s.pass_rate === null ? "N/A" : `${(s.pass_rate * 100).toFixed(1)}%`;
    console.log(
      `  ${s.date}   ${pad(t.pass)}  ${pad(t.fail)}  ${pad(t.pending)}      ${rate}`,
    );
  }
  console.log();
}

function pad(n) {
  return String(n).padStart(4);
}

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

// CI: GitHub Actions 잡 요약에 마크다운 표 append (env 있을 때만).
if (process.env.GITHUB_STEP_SUMMARY) {
  const rate =
    passRate === null ? "N/A (측정 0)" : `${(passRate * 100).toFixed(1)}%`;
  const md =
    `## LIVIQ evals\n\n` +
    `| verdict | count |\n| --- | --- |\n` +
    `| ✓ pass | ${tally.pass} |\n` +
    `| ✗ fail | ${tally.fail} |\n` +
    `| · pending | ${tally.pending} |\n` +
    `| total | ${tally.total} |\n\n` +
    `**pass-rate:** ${rate}\n`;
  appendFileSync(process.env.GITHUB_STEP_SUMMARY, md);
}

// 스냅샷 저장 — 부분 실행(--rule 필터)은 추이를 오염시키므로 전체 실행만 기록
if (!ruleFilter) {
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
}

// pending은 실패 아님(측정 불가). 실제 fail만 비제로 종료.
process.exit(tally.fail > 0 ? 1 : 0);
