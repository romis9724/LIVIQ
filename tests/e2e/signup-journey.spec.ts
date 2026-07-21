// 전 구간 가입 여정(H7-4, docs/09 §8.8) — 결정론(CI 게이트).
//
// 설치(SYS_ADMIN)→단지 생성→소장 초대·수락→직원 초대→명부 업로드→주민 이메일 가입·검증→
// 소장 승인→홈 진입, 그리고 명부 불일치 분기(불일치 배지·pending API 403)까지 한 여정으로 검증한다.
// AI 질의는 @llm 분리(signup-journey-ai.spec.ts).
//
// 각 역할은 자체 브라우저 컨텍스트에서 UI로 로그인한다(freshContext로 프로젝트 storageState=시드
// 활성 입주민 세션을 빈 상태로 덮어써 로그아웃 상태로 시작한다). 인증·초대 메일은 console 백엔드라
// 링크를 못 읽으므로, 원문을 아는 토큰을 pg로 직접 INSERT해 브라우저로 링크를 탄다(insertAuthToken).
//
// 멱등: globalSetup(seed.ts)과 beforeAll이 name LIKE 'E2E-%' 단지를 정리한다(리트라이는 새 워커에서
// beforeAll을 재실행하므로 globalSetup 미재실행에도 clean slate가 보장된다).

import path from "node:path";

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import type { Client } from "pg";

import { E2E, JOURNEY, MISMATCH_PERSON, PORTS, ROSTER_PERSON, SYS, maskName } from "./fixtures";
import {
  connectPg,
  findUserByEmail,
  insertAuthToken,
  seedJourneyHouseholds,
  wipeJourneyTenants,
} from "./seed";

const RESIDENT = `http://localhost:${PORTS.resident}`;
const ADMIN = `http://localhost:${PORTS.admin}`;
const API = `http://localhost:${PORTS.api}`;
const ROSTER_XLSX = path.join(__dirname, "fixtures", "roster-e2e.xlsx");

interface Applicant {
  readonly name: string;
  readonly birth: string;
  readonly dong: string;
  readonly ho: string;
}

/**
 * 로그아웃 상태의 새 컨텍스트 — 프로젝트 storageState(시드 활성 입주민 세션)를 명시적 빈 상태로
 * 덮어쓴다. browser.newContext()는 프로젝트 storageState를 상속하므로 그냥 두면 각 역할이 이미
 * 로그인된 채 시작한다(useRedirectIfAuthed가 /home으로 튕겨 여정이 성립하지 않는다).
 */
async function freshContext(browser: Browser): Promise<BrowserContext> {
  return browser.newContext({ storageState: { cookies: [], origins: [] } });
}

/** 관리자 콘솔 로그인(web-admin). 성공 시 window.location="/" → 역할별 첫 진입으로 라우팅된다. */
async function adminLogin(page: Page, email: string, password: string): Promise<void> {
  await page.goto(`${ADMIN}/login`);
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "로그인" }).click();
}

/** 입주민 앱 로그인(web-resident). 성공 시 루트(/)가 /me 상태로 화면을 분기한다. */
async function residentLogin(page: Page, email: string, password: string): Promise<void> {
  await page.goto(`${RESIDENT}/login`);
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "로그인" }).click();
}

/**
 * 주민 계정 가입 → 검증 메일 안내 화면까지 (H7-5).
 * via="picker"면 로그인 화면 회원가입 버튼 → 단지 선택(정본 UX),
 * via="link"면 가입 링크(?t=) 사전 선택 딥링크 경로를 검증한다.
 */
async function signupResident(
  page: Page,
  tenantId: string,
  email: string,
  password: string,
  via: "picker" | "link" = "picker",
): Promise<void> {
  if (via === "picker") {
    await page.goto(`${RESIDENT}/login`);
    await page.getByRole("button", { name: "회원가입" }).click();
    await expect(page).toHaveURL(/\/signup/);
    await page.getByLabel("단지").selectOption(JOURNEY.tenantName);
  } else {
    await page.goto(`${RESIDENT}/signup?t=${tenantId}`);
    // 사전 선택 확인 — 링크의 단지가 select에 반영되어 있어야 한다.
    await expect(page.getByLabel("단지")).toHaveValue(tenantId);
  }
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByLabel("비밀번호 확인").fill(password);
  await page.getByRole("button", { name: "가입하기" }).click();
  await expect(page.getByText("인증 메일을 보냈습니다")).toBeVisible();
}

/** 알려진 검증 토큰 INSERT → 링크 방문(302 /login?verified=1) → 로그인 → 온보딩 진입. */
async function verifyAndLogin(
  page: Page,
  pg: Client,
  email: string,
  verifyToken: string,
  password: string,
): Promise<void> {
  const user = await findUserByEmail(pg, email);
  if (!user) throw new Error(`가입 계정을 찾을 수 없습니다: ${email}`);
  await insertAuthToken(pg, {
    tenantId: user.tenantId,
    userId: user.id,
    purpose: "verify_email",
    raw: verifyToken,
  });

  await page.goto(`${API}/auth/verify-email?token=${verifyToken}`);
  await expect(page).toHaveURL(/\/login\?verified=1/);
  await expect(page.getByText("이메일 인증이 완료되었습니다. 로그인해 주세요.")).toBeVisible();

  await residentLogin(page, email, password);
  await expect(page).toHaveURL(/\/onboarding/);
}

/** 온보딩 — 약관 전체 동의 → 성함·생년월일·동·호 입력 → /pending(승인 대기) 도달. */
async function completeOnboarding(page: Page, person: Applicant): Promise<void> {
  await page.getByRole("checkbox").first().check(); // 전체 동의(필수+선택)
  await page.getByRole("button", { name: "다음" }).click();

  await page.getByLabel("성명").fill(person.name);
  await page.getByLabel("생년월일").fill(person.birth);
  await page.locator("#signup-dong").selectOption(person.dong);
  await page.locator("#signup-ho").selectOption(person.ho);
  await page.getByRole("button", { name: "가입 신청" }).click();

  await expect(page).toHaveURL(/\/pending/);
  await expect(page.getByText("관리소장 승인을 기다리고 있어요")).toBeVisible();
}

/** UI로 생성한 여정 단지의 id — 정리 로직이 중복을 막으므로 정확히 1건이어야 한다. */
async function tenantIdByName(pg: Client, name: string): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(`SELECT id FROM tenants WHERE name = $1`, [name]);
  if (rows.length !== 1) throw new Error(`단지 '${name}' 행 ${rows.length}건 (1건이어야 함)`);
  return rows[0].id;
}

// 여정을 직렬 단계로 나눈다 — 각 단계가 자체 test timeout(90s)을 받아 Next dev 첫 라우트 컴파일이
// 누적돼도 여유롭다. workers=1·serial이라 모듈 스코프로 단지 id·컨텍스트를 단계 간 공유한다.
test.describe.serial("가입 전 구간 여정 — 설치→단지→초대→명부→가입→승인 (H7-4)", () => {
  let pg: Client;
  let journeyTenantId: string;
  let mgrCtx: BrowserContext | undefined;
  let mgrPage: Page; // 소장 — 단계 2~5 공유
  let applicantCtx: BrowserContext | undefined;
  let applicant: Page; // 명부 일치 주민 — 단계 3~4 공유

  test.beforeAll(async () => {
    pg = await connectPg();
    // 리트라이(새 워커)는 globalSetup을 재실행하지 않으므로 여기서 여정 단지를 다시 정리한다.
    await wipeJourneyTenants(pg);
  });

  test.afterAll(async () => {
    await mgrCtx?.close();
    await applicantCtx?.close();
    await pg?.end();
  });

  test("SYS_ADMIN이 단지를 만들고 소장을 초대한다", async ({ browser }) => {
    const sys = await freshContext(browser);
    const sysPage = await sys.newPage();
    await adminLogin(sysPage, SYS.email, E2E.password); // SYS_ADMIN 비번 = 시드 PASSWORD_HASH
    await expect(sysPage).toHaveURL(/\/system\/tenants/); // SYS_ADMIN 첫 진입=단지 관리

    await sysPage.getByLabel("단지 이름").fill(JOURNEY.tenantName);
    await sysPage.getByRole("button", { name: "단지 생성" }).click();
    const tenantRow = sysPage.locator(".tn-row").filter({ hasText: JOURNEY.tenantName });
    await expect(tenantRow).toBeVisible();

    // 생성 직후 세대 시드 — 명부 업로드·온보딩의 세대 조회 전제(신규 단지엔 building이 없다).
    journeyTenantId = await tenantIdByName(pg, JOURNEY.tenantName);
    await seedJourneyHouseholds(pg, journeyTenantId);

    // 소장 초대(UI 폼, 202) → 알려진 초대 토큰 INSERT.
    await tenantRow.getByLabel("소장 초대 이메일").fill(JOURNEY.managerEmail);
    await tenantRow.getByRole("button", { name: "소장 초대" }).click();
    await expect(sysPage.getByText("소장 초대 메일을 발송했습니다", { exact: false })).toBeVisible();
    // 초대 후 행이 현재 소장(수락 대기) 표시로 전환된다 — 단지당 소장 1명(H7-6).
    await expect(tenantRow.getByText("수락 대기")).toBeVisible();

    const manager = await findUserByEmail(pg, JOURNEY.managerEmail);
    if (!manager) throw new Error("초대된 소장 계정이 생성되지 않았습니다");
    await insertAuthToken(pg, {
      tenantId: manager.tenantId,
      userId: manager.id,
      purpose: "invite",
      raw: JOURNEY.inviteToken,
    });

    await sys.close();
  });

  test("소장이 초대를 수락하고 직원 초대·명부 업로드를 한다", async ({ browser }) => {
    mgrCtx = await freshContext(browser);
    mgrPage = await mgrCtx.newPage();

    // 초대 수락(비밀번호 설정) → 로그인.
    await mgrPage.goto(`${ADMIN}/invite?token=${JOURNEY.inviteToken}`);
    await mgrPage.getByLabel("새 비밀번호", { exact: true }).fill(JOURNEY.password);
    await mgrPage.getByLabel("새 비밀번호 확인").fill(JOURNEY.password);
    await mgrPage.getByRole("button", { name: "계정 활성화" }).click();
    await expect(mgrPage.getByText("계정이 활성화되었습니다")).toBeVisible();

    await adminLogin(mgrPage, JOURNEY.managerEmail, JOURNEY.password);
    await expect(mgrPage).toHaveURL(/\/dashboard/); // MANAGER 첫 진입=대시보드(H7-6)

    // 직원 초대(202) → 목록에 초대됨 행.
    await mgrPage.goto(`${ADMIN}/staff`);
    await mgrPage.getByLabel("직원 이메일").fill(JOURNEY.staffEmail);
    await mgrPage.getByRole("button", { name: "직원 초대" }).click();
    await expect(mgrPage.getByText("직원 초대 메일을 발송했습니다", { exact: false })).toBeVisible();
    await expect(mgrPage.getByText("초대됨")).toBeVisible();

    // 명부 업로드(신규 1건 — 김입주/101동 3층 301호).
    await mgrPage.goto(`${ADMIN}/approvals`);
    await expect(mgrPage.getByText("대기 중인 가입 신청이 없습니다")).toBeVisible();
    await mgrPage.setInputFiles('input[type="file"]', ROSTER_XLSX);
    await expect(mgrPage.getByText("신규 등록 1")).toBeVisible();
  });

  test("명부 일치 주민이 가입·검증·온보딩한다", async ({ browser }) => {
    applicantCtx = await freshContext(browser);
    applicant = await applicantCtx.newPage();
    await signupResident(applicant, journeyTenantId, JOURNEY.applicantEmail, JOURNEY.password);
    await verifyAndLogin(
      applicant,
      pg,
      JOURNEY.applicantEmail,
      JOURNEY.applicantVerifyToken,
      JOURNEY.password,
    );
    await completeOnboarding(applicant, ROSTER_PERSON);
  });

  test("소장이 명부 일치를 승인하면 주민이 홈에 진입한다", async () => {
    await mgrPage.goto(`${ADMIN}/approvals`);
    const matchedCard = mgrPage
      .locator(".apv-card")
      .filter({ hasText: maskName(ROSTER_PERSON.name) });
    await expect(matchedCard).toBeVisible();
    await expect(matchedCard.getByText("명부 일치")).toBeVisible();
    await matchedCard.getByRole("button", { name: "승인" }).click();
    await expect(mgrPage.getByText("승인 완료", { exact: false })).toBeVisible();

    // 승인으로 대기 세션 revoke(ADR-0011) → 주민 재로그인 → 활성 → 홈.
    await residentLogin(applicant, JOURNEY.applicantEmail, JOURNEY.password);
    await expect(applicant).toHaveURL(/\/home/);
    await expect(applicant.getByText("무엇이든 물어보세요")).toBeVisible();
  });

  test("명부 불일치 주민은 대기 상태로 표시되고 일반 API가 차단된다", async ({ browser }) => {
    const mismatchCtx = await freshContext(browser);
    const mismatch = await mismatchCtx.newPage();
    await signupResident(mismatch, journeyTenantId, JOURNEY.mismatchEmail, JOURNEY.password, "link");
    await verifyAndLogin(
      mismatch,
      pg,
      JOURNEY.mismatchEmail,
      JOURNEY.mismatchVerifyToken,
      JOURNEY.password,
    );
    await completeOnboarding(mismatch, MISMATCH_PERSON);

    await mgrPage.goto(`${ADMIN}/approvals`);
    const mismatchCard = mgrPage
      .locator(".apv-card")
      .filter({ hasText: maskName(MISMATCH_PERSON.name) });
    await expect(mismatchCard).toBeVisible();
    await expect(mismatchCard.getByText("명부 불일치", { exact: false })).toBeVisible();

    // 승인 전 pending은 일반 API 차단 — 서버가 403(get_context, docs/06 §2).
    const blocked = await mismatch.request.get(`${API}/notices`);
    expect(blocked.status()).toBe(403);

    await mismatchCtx.close();
  });
});
