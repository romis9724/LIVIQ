#!/usr/bin/env node
/**
 * check-context-paths.mjs
 *
 * AI 컨텍스트 문서(CLAUDE.md / README / ARCHITECTURE / docs)에 적힌
 * 상대경로 마크다운 링크가 실제로 존재하는지 검증한다.
 * hallucinated path(stale 참조)를 머지·푸시 시점에 차단하는 것이 목적.
 *
 * - stdlib only, 의존성 없음 (Node >=20)
 * - 검사 대상: 마크다운 링크 `](path)` 중 상대경로만
 * - 제외: http(s)://, mailto:, 앵커(#...), 절대경로(/...)
 * - 링크 뒤 `#anchor` / `§` 표기는 파일 존재 여부만 확인
 *
 * 종료 코드: 깨진 경로 있으면 1, 없으면 0.
 */

import { readFileSync, existsSync, statSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

// 검사할 컨텍스트 문서 수집: 루트 마크다운 + 모든 CLAUDE.md + docs/*.md
function collectDocs() {
  const out = execSync(
    `git -C "${ROOT}" ls-files "*.md" "**/CLAUDE.md" "CLAUDE.md"`,
    { encoding: "utf8" },
  );
  const files = new Set(
    out
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      // node_modules 방어 (git ls-files는 tracked만 반환하나 이중 안전)
      .filter((f) => !f.includes("node_modules/")),
  );
  return [...files];
}

// 마크다운 링크 타깃 추출: ](target)
const LINK_RE = /\]\(([^)]+)\)/g;

function isExternal(target) {
  return (
    /^[a-z]+:\/\//i.test(target) ||
    target.startsWith("mailto:") ||
    target.startsWith("#") ||
    target.startsWith("/")
  );
}

function normalizeTarget(target) {
  // 앵커·쿼리 제거, 공백 트림
  return target.split("#")[0].split("?")[0].trim();
}

const broken = [];
let checked = 0;

for (const rel of collectDocs()) {
  const abs = join(ROOT, rel);
  let text;
  try {
    text = readFileSync(abs, "utf8");
  } catch {
    continue;
  }
  const baseDir = dirname(abs);
  let m;
  while ((m = LINK_RE.exec(text)) !== null) {
    const raw = m[1];
    if (isExternal(raw)) continue;
    const target = normalizeTarget(raw);
    if (!target) continue; // 순수 앵커
    checked++;
    const resolved = resolve(baseDir, target);
    if (!existsSync(resolved)) {
      broken.push({ doc: rel, target: raw });
    } else {
      // 디렉토리 링크는 존재만 확인
      statSync(resolved);
    }
  }
}

if (broken.length > 0) {
  console.error(
    `\n✗ 컨텍스트 문서에 깨진 경로 ${broken.length}건 (검사 ${checked}건):\n`,
  );
  for (const b of broken) {
    console.error(`  ${b.doc}  →  ${b.target}`);
  }
  console.error(
    `\n수정 후 다시 시도. stale 참조는 없는 것보다 나쁘다.\n`,
  );
  process.exit(1);
}

console.log(`✓ 컨텍스트 경로 검증 통과 (${checked}건, 깨진 경로 0).`);
