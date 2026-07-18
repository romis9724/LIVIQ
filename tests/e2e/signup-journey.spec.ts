// 전 구간 가입 여정(H6-4, docs/09 §8.7) — 결정론(CI 게이트).
//
// 명부 업로드 → 신규 로그인·가입 신청(명부 일치) → 관리자 승인 → 재로그인 →
// 홈·공지·관리비·민원·알림함 → 명부 불일치 분기(pending·API 차단)까지 한 여정으로 검증한다.
//
// 신규 가입자는 시드 활성 사용자(storageState)와 다른 신원이라 자체 브라우저 컨텍스트에서
// 로그인한다. 신원(sub)은 mock IdP의 mock_sub 쿠키로 지정한다(mock-idp.mjs 참고).
//
// 멱등: beforeAll 이 E2E 단지를 전체 wipe·재시드한다(여정이 생성한 pre_registered·가입 계정 포함).
// 리트라이는 새 워커에서 beforeAll 을 재실행하므로 clean slate 가 보장된다.

import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  E2E,
  FEE_CURRENT_TOTAL,
  INVITE_CODE,
  MISMATCH_PERSON,
  NOTICE1,
  PORTS,
  ROSTER_PERSON,
  maskName,
} from "./fixtures";
import reseed from "./seed";

const RESIDENT = `http://localhost:${PORTS.resident}`;
const ADMIN = `http://localhost:${PORTS.admin}`;
const API = `http://localhost:${PORTS.api}`;
const MOCK_IDP = "http://localhost:9099";
const ROSTER_XLSX = path.join(__dirname, "fixtures", "roster-e2e.xlsx");

/** FeesView.formatWon 과 동일 표기. */
function won(n: number): string {
  return `${n.toLocaleString("ko-KR")}원`;
}

/** storageState 없는(세션 미보유) 컨텍스트 — mock_sub 쿠키로 신규 신원을 지정한다. */
async function freshResident(browser: Browser, sub: string): Promise<Page> {
  const context = await browser.newContext();
  await context.addCookies([{ name: "mock_sub", value: sub, url: MOCK_IDP }]);
  return context.newPage();
}

interface Applicant {
  readonly name: string;
  readonly birth: string;
  readonly dong: string;
  readonly ho: string;
}

/** 신규 로그인(온보딩 세션) 후 약관 동의·정보 입력으로 가입 신청 → /pending 도달. */
async function completeSignup(page: Page, person: Applicant): Promise<void> {
  await page.goto(`${API}/auth/google/login`);
  await expect(page).toHaveURL(/\/onboarding/);

  // 1단계 약관 — 전체 동의(첫 체크박스)로 필수·선택 모두 동의.
  await page.getByRole("checkbox").first().check();
  await page.getByRole("button", { name: "다음" }).click();

  // 2단계 정보 입력.
  await page.getByLabel("단지 초대코드").fill(INVITE_CODE);
  await page.getByLabel("성명").fill(person.name);
  await page.getByLabel("생년월일").fill(person.birth);
  await page.locator("#signup-dong").selectOption(person.dong);
  await page.locator("#signup-ho").selectOption(person.ho);
  await page.getByRole("button", { name: "가입 신청" }).click();

  await expect(page).toHaveURL(/\/pending/);
  await expect(page.getByText("관리소장 승인을 기다리고 있어요")).toBeVisible();
}

test.beforeAll(async () => {
  await reseed();
});

test("명부 업로드→가입 신청→승인→재로그인→앱 이용, 그리고 불일치 분기", async ({
  page,
  browser,
}) => {
  // ── 1. 관리자: 명부 엑셀 업로드 → 사전등록 1건 생성(리포트 확인) ──
  await page.goto(`${ADMIN}/approvals`);
  // 대기 목록 조회가 끝난 뒤 업로드 — 재시드 직후 첫 요청 2건이 단지 DEK를 동시 최초생성하며
  // 경합(tenant_keys uq)하지 않도록 직렬화한다(목록 로드가 DEK를 먼저 확정).
  await expect(page.getByText("대기 중인 가입 신청이 없습니다")).toBeVisible();
  await page.setInputFiles('input[type="file"]', ROSTER_XLSX);
  await expect(page.getByText("신규 등록 1")).toBeVisible();

  // ── 2. 신규 가입자(명부 일치): 로그인 → 가입 신청 → 대기 ──
  const applicant = await freshResident(browser, E2E.signupSub);
  await completeSignup(applicant, ROSTER_PERSON);

  // ── 3. 관리자: 대기 목록에 마스킹 이름·명부 일치로 표시 → 승인 ──
  await page.goto(`${ADMIN}/approvals`);
  await expect(page.getByText(maskName(ROSTER_PERSON.name))).toBeVisible();
  await expect(page.getByText("명부 일치")).toBeVisible();
  await page.getByRole("button", { name: "승인" }).click();
  await expect(page.getByText("승인 완료", { exact: false })).toBeVisible();

  // ── 4. 신규 가입자: 재로그인(승인으로 이전 세션 revoke됨) → 활성 → 홈 ──
  await applicant.goto(`${API}/auth/google/login`);
  await expect(applicant).toHaveURL(/\/home/);
  await expect(applicant.getByText("무엇이든 물어보세요")).toBeVisible();

  // 공지 — 발행 공지가 목록에 표시.
  await applicant.goto(`${RESIDENT}/notices`);
  await expect(
    applicant.locator(".notice-card").filter({ hasText: NOTICE1.title }),
  ).toBeVisible();

  // 관리비 — 세대(301호) 확정 관리비 합계 표시(표시 전용).
  await applicant.goto(`${RESIDENT}/fees`);
  await expect(
    applicant.getByText(won(FEE_CURRENT_TOTAL)).first(),
  ).toBeVisible();

  // 민원 접수 — 폼 제출 후 접수 확인.
  await applicant.goto(`${RESIDENT}/inquiries`);
  await applicant.getByRole("tab", { name: "접수하기" }).click();
  const inquiryTitle = `E2E 가입 여정 민원 ${Date.now()}`;
  await applicant.getByLabel("제목").fill(inquiryTitle);
  await applicant
    .getByLabel("상세 내용")
    .fill("가입 직후 접수한 테스트 민원입니다.");
  await applicant.getByRole("button", { name: "접수하기" }).click();
  await expect(applicant.getByText("민원을 접수했습니다.")).toBeVisible();

  // 나 > 알림함 — 승인 알림 도착.
  await applicant.goto(`${RESIDENT}/me`);
  await expect(applicant.getByText("가입이 승인되었습니다")).toBeVisible();

  // ── 5. 불일치 분기: 명부에 없는 정보로 가입 → 대기(수동 확인) ──
  const mismatch = await freshResident(browser, E2E.mismatchSub);
  await completeSignup(mismatch, MISMATCH_PERSON);

  // 관리자 목록에 "명부 불일치"로 분류(roster_matched=false).
  await page.goto(`${ADMIN}/approvals`);
  await expect(page.getByText(maskName(MISMATCH_PERSON.name))).toBeVisible();
  await expect(page.getByText("명부 불일치", { exact: false })).toBeVisible();

  // 승인 전에는 일반 API 차단(pending 상태) — 서버가 403으로 막는다.
  const blocked = await mismatch.request.get(`${API}/notices`);
  expect(blocked.status()).toBe(403);

  await applicant.context().close();
  await mismatch.context().close();
});
