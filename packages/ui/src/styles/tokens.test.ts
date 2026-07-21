// 토큰 정합 가드 — 레포 전체 CSS의 var(--x) 사용이 전부 정의되어 있는지 검사.
// 미정의 변수는 해당 선언 전체를 조용히 무효화한다(H7-5에서 --space-5 미정의로
// 목록 카드 padding이 0이 되어 화면이 깨졌던 회귀의 재발 방지).

import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const REPO_ROOT = path.resolve(__dirname, "../../../..");
const SCAN_DIRS = ["apps", "packages"];
const SKIP_DIRS = new Set(["node_modules", ".next", ".turbo", "dist", "coverage"]);

function collectCssFiles(dir: string, out: string[]): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) collectCssFiles(full, out);
    } else if (entry.name.endsWith(".css")) {
      out.push(full);
    }
  }
}

describe("디자인 토큰 정합", () => {
  it("모든 var(--x) 사용은 정의된 커스텀 프로퍼티여야 한다", () => {
    const files: string[] = [];
    for (const dir of SCAN_DIRS) collectCssFiles(path.join(REPO_ROOT, dir), files);
    expect(files.length).toBeGreaterThan(0);

    const defined = new Set<string>();
    const used = new Map<string, Set<string>>();
    for (const file of files) {
      const css = fs.readFileSync(file, "utf8");
      for (const m of css.matchAll(/(--[a-z0-9-]+)\s*:/g)) defined.add(m[1]);
      for (const m of css.matchAll(/var\(\s*(--[a-z0-9-]+)\s*[),]/g)) {
        if (!used.has(m[1])) used.set(m[1], new Set());
        used.get(m[1])!.add(path.relative(REPO_ROOT, file));
      }
    }

    const undefinedUsages = [...used]
      .filter(([name]) => !defined.has(name))
      .map(([name, where]) => `${name} ← ${[...where].join(", ")}`);
    expect(undefinedUsages, `미정의 토큰 사용:\n${undefinedUsages.join("\n")}`).toEqual([]);
  });
});
