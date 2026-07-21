// 세션 로그인 셋업 — 이메일+비밀번호로 로그인해 세션 쿠키를 storageState로 저장 (H7-1).
//
// 여정 스펙은 이 storageState를 재사용해 세션 쿠키 인증으로 api를 호출한다(dev 헤더 폐기).
// globalSetup(seed.ts)이 login_id=E2E.email HMAC·email_verified_at 기록된 active user를 먼저 심는다.

import fs from "node:fs";
import path from "node:path";

import { expect, test as setup } from "@playwright/test";

import { E2E, PORTS, STORAGE_STATE } from "./fixtures";

setup("이메일+비밀번호 로그인 → 세션 쿠키 저장", async ({ request }) => {
  // POST /auth/login → 200 + Set-Cookie(liviq_session). APIRequestContext가 쿠키를 저장소에 수집한다.
  const response = await request.post(`http://localhost:${PORTS.api}/auth/login`, {
    data: { email: E2E.email, password: E2E.password },
  });
  expect(response.ok(), "로그인이 200으로 성공해야 함").toBeTruthy();

  const state = await request.storageState();
  const hasSession = state.cookies.some((cookie) => cookie.name === "liviq_session");
  expect(hasSession, "세션 쿠키(liviq_session)가 발급되어야 함").toBe(true);

  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });
  await request.storageState({ path: STORAGE_STATE });
});
