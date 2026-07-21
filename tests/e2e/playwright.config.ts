// Playwright 설정 — 결정론 여정(docs/07 §4, docs/09 §8.2 H2-7).
//
// 결정론 원칙: 임의 timeout 금지, expect 기반 대기. chromium 단일.
// @llm 태그 여정(비서 질의·폴백)은 임베딩 LLM 필요 — CI에선 grepInvert로 제외하고
// 로컬(Ollama)에서만 실행한다.

import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

import { PORTS, STORAGE_STATE } from "./fixtures";

const HERE = __dirname;
const REPO_ROOT = path.resolve(HERE, "..", "..");
const API_DIR = path.join(REPO_ROOT, "apps", "api");

const isCI = !!process.env.CI;

// PII_MASTER_KEY — 32byte base64 더미(ADR-0010 fail-closed 검증용, apps/api conftest 패턴).
// seed.ts 가 login_id(이메일 HMAC) 계산에 동일 키를 쓴다(같은 기본값 폴백).
const PII_MASTER_KEY = Buffer.alloc(32, 0).toString("base64");

const OLLAMA = process.env.LLM_BASE_URL ?? "http://localhost:11434/v1";

const apiEnv: Record<string, string> = {
  API_ENV: "local",
  DATABASE_URL:
    process.env.DATABASE_URL ??
    "postgresql+asyncpg://liviq:liviq@localhost:15432/liviq",
  REDIS_URL: process.env.REDIS_URL ?? "redis://localhost:6381",
  S3_ENDPOINT_URL: process.env.S3_ENDPOINT_URL ?? "http://localhost:9002",
  S3_ACCESS_KEY_ID: process.env.S3_ACCESS_KEY_ID ?? "e2e",
  S3_SECRET_ACCESS_KEY: process.env.S3_SECRET_ACCESS_KEY ?? "e2e",
  // 스토리지 인메모리 — 명부 업로드(H6-4)가 S3에 원본을 archive하는데 e2e(CI 포함)는 MinIO를
  // 기동하지 않는다. 여정은 archive 파일을 되읽지 않으므로 인메모리로 충분(deps.get_storage).
  STORAGE_BACKEND: "memory",
  PII_MASTER_KEY: process.env.PII_MASTER_KEY ?? PII_MASTER_KEY,
  // @llm 여정에서만 실제 호출 — 그 외 여정은 boot 시 lazy라 사용 안 됨.
  LLM_BASE_URL: OLLAMA,
  LLM_MODEL: process.env.LLM_MODEL ?? "qwen2.5:7b-instruct",
  EMBEDDING_BASE_URL: process.env.EMBEDDING_BASE_URL ?? OLLAMA,
  EMBEDDING_MODEL: process.env.EMBEDDING_MODEL ?? "bge-m3",
  // 인증 메일(검증·재설정) — 발송 없이 링크를 로그로만 출력(ADR-0014). E2E는 실 SMTP 미사용.
  MAIL_BACKEND: "console",
  // 이메일 검증·재설정 링크가 웹 앱으로 복귀 + credentials CORS 허용 오리진.
  WEB_BASE_URL: `http://localhost:${PORTS.resident}`,
  WEB_ORIGINS: `http://localhost:${PORTS.resident},http://localhost:${PORTS.admin}`,
};

// 웹 앱은 세션 쿠키 인증만 사용(dev 헤더 미주입 — NEXT_PUBLIC_DEV_* 제거).
const webEnv: Record<string, string> = {
  NEXT_PUBLIC_API_BASE_URL: `http://localhost:${PORTS.api}`,
};

export default defineConfig({
  testDir: HERE,
  globalSetup: path.join(HERE, "seed.ts"),
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,
  // Next dev 첫 라우트 컴파일이 느려 네비게이션·테스트 타임아웃을 넉넉히.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: isCI ? [["list"], ["html", { open: "never" }]] : "list",
  // CI는 임베딩 LLM이 없으므로 @llm 여정 제외(로컬은 전체 실행).
  grepInvert: isCI ? /@llm/ : undefined,
  use: {
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    navigationTimeout: 60_000,
  },
  projects: [
    // 세션 로그인 셋업 — storageState 생성. 여정 프로젝트가 의존한다.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: STORAGE_STATE },
      dependencies: ["setup"],
    },
  ],
  webServer: [
    {
      command: "uv run --no-sync uvicorn app.main:app --port 8000",
      cwd: API_DIR,
      url: `http://localhost:${PORTS.api}/health`,
      env: apiEnv,
      reuseExistingServer: !isCI,
      timeout: 120_000,
    },
    {
      command: "pnpm --filter @liviq/web-resident dev",
      cwd: REPO_ROOT,
      url: `http://localhost:${PORTS.resident}`,
      env: webEnv,
      reuseExistingServer: !isCI,
      timeout: 180_000,
    },
    {
      command: "pnpm --filter @liviq/web-admin dev",
      cwd: REPO_ROOT,
      url: `http://localhost:${PORTS.admin}`,
      env: webEnv,
      reuseExistingServer: !isCI,
      timeout: 180_000,
    },
  ],
});
