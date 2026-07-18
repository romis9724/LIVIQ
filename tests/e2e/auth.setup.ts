// 세션 로그인 셋업 — mock IdP로 로그인해 세션 쿠키를 storageState로 저장 (H6-1).
//
// 여정 스펙은 이 storageState를 재사용해 세션 쿠키 인증으로 api를 호출한다(dev 헤더 폐기).
// globalSetup(seed.ts)이 login_id=E2E.googleSub인 active user를 먼저 심는다.

import fs from "node:fs";
import path from "node:path";

import { expect, test as setup } from "@playwright/test";

import { PORTS, STORAGE_STATE } from "./fixtures";

setup("mock IdP 로그인 → 세션 쿠키 저장", async ({ request }) => {
  // /auth/google/login → mock IdP /authorize → /auth/google/callback(세션 쿠키 발급) → 웹 복귀.
  // APIRequestContext가 리다이렉트 체인을 따라가며 Set-Cookie를 쿠키 저장소에 수집한다.
  const response = await request.get(`http://localhost:${PORTS.api}/auth/google/login`);
  expect(response.ok(), "로그인 리다이렉트 체인이 200으로 끝나야 함").toBeTruthy();

  const state = await request.storageState();
  const hasSession = state.cookies.some((cookie) => cookie.name === "liviq_session");
  expect(hasSession, "세션 쿠키(liviq_session)가 발급되어야 함").toBe(true);

  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });
  await request.storageState({ path: STORAGE_STATE });
});
