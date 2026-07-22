// 역할별 병렬 시각 스윕 — 독립 브라우저 context(쿠키 격리)로 동시에 로그인해
// 주요 화면을 데스크톱·모바일 스크린샷으로 뜬다. CI 게이트 아님(로컬 QA 도구).
//
// 사용:  pnpm --filter @liviq/e2e visual            # demo 3역할
//        SWEEP_SYSADMIN_EMAIL=.. SWEEP_SYSADMIN_PASSWORD=.. pnpm --filter @liviq/e2e visual
// 출력:  tests/e2e/.visual-sweep/<역할>-<라우트>-<뷰포트>.png (SWEEP_OUT으로 변경 가능)
//
// 전제: dev 서버 3종(8000·3000·3001) 기동 + seed_demo 계정.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const API = "http://localhost:8000";
const RESIDENT = "http://localhost:3000";
const ADMIN = "http://localhost:3001";
const DEMO_PASSWORD = "liviq-demo-1234!"; // seed_demo 공개 데모 계정(시크릿 아님)

const OUT = process.env.SWEEP_OUT
  ? path.resolve(process.env.SWEEP_OUT)
  : path.join(path.dirname(fileURLToPath(import.meta.url)), "..", ".visual-sweep");

const VIEWPORTS = [
  { tag: "desktop", width: 1280, height: 860 },
  { tag: "mobile", width: 375, height: 812 },
];

const ROLES = [
  {
    name: "manager",
    email: "demo-manager@example.com",
    password: DEMO_PASSWORD,
    base: ADMIN,
    routes: ["/dashboard", "/residents", "/staff", "/fees"],
  },
  {
    name: "staff",
    email: "demo-staff@example.com",
    password: DEMO_PASSWORD,
    base: ADMIN,
    routes: ["/inquiries", "/notices/new", "/documents"],
  },
  {
    name: "resident",
    email: "demo-resident@example.com",
    password: DEMO_PASSWORD,
    base: RESIDENT,
    routes: ["/home", "/assistant", "/fees", "/notices", "/me"],
  },
];

// SYS_ADMIN은 로컬 비밀번호가 레포에 없으므로 env로만 주입(하드코딩 금지).
if (process.env.SWEEP_SYSADMIN_EMAIL && process.env.SWEEP_SYSADMIN_PASSWORD) {
  ROLES.push({
    name: "sysadmin",
    email: process.env.SWEEP_SYSADMIN_EMAIL,
    password: process.env.SWEEP_SYSADMIN_PASSWORD,
    base: ADMIN,
    routes: ["/system/tenants"],
  });
}

/** 한 역할×뷰포트 — 독립 context에 API 로그인 후 라우트 순회 스크린샷. */
async function sweepRole(browser, role, viewport) {
  const context = await browser.newContext({ viewport });
  try {
    const login = await context.request.post(`${API}/auth/login`, {
      data: { email: role.email, password: role.password },
    });
    if (!login.ok()) throw new Error(`${role.name} 로그인 실패: HTTP ${login.status()}`);

    const page = await context.newPage();
    const shots = [];
    for (const route of role.routes) {
      await page.goto(`${role.base}${route}`, { waitUntil: "networkidle" });
      const slug = route.replaceAll("/", "-").replace(/^-/, "") || "root";
      const file = path.join(OUT, `${role.name}-${slug}-${viewport.tag}.png`);
      await page.screenshot({ path: file, fullPage: true });
      shots.push(file);
    }
    return { role: role.name, viewport: viewport.tag, shots, ok: true };
  } finally {
    await context.close();
  }
}

const started = Date.now();
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const jobs = ROLES.flatMap((role) => VIEWPORTS.map((viewport) => sweepRole(browser, role, viewport)));
const results = await Promise.allSettled(jobs);
await browser.close();

let failed = 0;
for (const result of results) {
  if (result.status === "fulfilled") {
    const { role, viewport, shots } = result.value;
    console.log(`✓ ${role} (${viewport}) — ${shots.length}장`);
  } else {
    failed += 1;
    console.error(`✗ ${result.reason}`);
  }
}
console.log(`${results.length - failed}/${results.length} 스윕 완료 in ${((Date.now() - started) / 1000).toFixed(1)}s → ${OUT}`);
process.exit(failed > 0 ? 1 : 0);
