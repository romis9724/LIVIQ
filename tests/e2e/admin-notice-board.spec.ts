// 관리자 공지 게시판 여정 — 작성·즉시 발행→목록 확인→상세 첨부 업로드→입주민이 제목·첨부 확인.
// 결정론(CI 게이트, @llm 아님). 시드 계정 세션(auth.setup.ts storageState)은 MANAGER·RESIDENT를
// 겸해 web-admin·web-resident 양쪽 API 호출을 같은 세션 쿠키로 통과한다(admin-facilities.spec 관례).
import path from "node:path";

import { expect, test } from "@playwright/test";

import { PORTS } from "./fixtures";

const ADMIN = `http://localhost:${PORTS.admin}`;
const RESIDENT = `http://localhost:${PORTS.resident}`;
// 픽스처 첨부(수 KB PDF — 20MB 상한 아래). 다운로드 자체는 pytest가 커버, 여기선 파일명 노출만 확인.
const ATTACHMENT = path.join(__dirname, "fixtures", "notice-attach-e2e.pdf");
const ATTACHMENT_NAME = "notice-attach-e2e.pdf";

test("관리자가 공지를 작성·발행하면 첨부를 붙일 수 있고 입주민이 제목·첨부를 본다", async ({
  page,
}) => {
  // 리트라이(globalSetup 미재실행)에도 안 겹치도록 제목에 타임스탬프를 붙인다(admin-facilities 관례).
  const title = `E2E 게시판 공지 ${Date.now()}`;
  const body = "게시판 전환 후 첫 공지입니다. 첨부 파일을 확인해 주세요.";

  // ── 작성 → 즉시 발행 ──
  await page.goto(`${ADMIN}/notices/new`);
  await page.getByLabel("제목").fill(title);
  await page.getByLabel("본문").fill(body);
  await page.getByRole("switch", { name: "상단 고정" }).click(); // 고정 → 입주민 화면 배지 검증
  await page.getByRole("radio", { name: /즉시 발행/ }).check();
  await page.getByRole("button", { name: "발행하기" }).click();

  // 발행 성공 → 저장 토스트 + 상세(수정) 화면으로 이동.
  await expect(page.getByText("공지를 저장했습니다", { exact: false })).toBeVisible();
  await expect(page).toHaveURL(/\/notices\/[0-9a-f-]{36}$/);

  // ── 목록에서 확인(발행 배지 + 제목 링크) ──
  await page.goto(`${ADMIN}/notices`);
  const row = page.locator("tr").filter({ hasText: title });
  await expect(row).toBeVisible();
  await expect(row.locator(".notice-badge--published")).toBeVisible();

  // ── 상세 진입 → 첨부 업로드 ──
  await row.getByRole("link", { name: title }).click();
  await expect(page.getByRole("heading", { name: "첨부 파일" })).toBeVisible();
  await page.setInputFiles('input[type="file"]', ATTACHMENT);
  await expect(page.getByText("첨부를 추가했습니다.")).toBeVisible();
  await expect(page.getByText(ATTACHMENT_NAME)).toBeVisible();

  // ── 입주민이 목록·상세에서 제목·첨부 파일명을 본다 ──
  await page.goto(`${RESIDENT}/notices`);
  const card = page.locator(".notice-card").filter({ hasText: title });
  await expect(card).toBeVisible();
  await expect(card.getByText("📌 고정")).toBeVisible();
  await expect(card.getByLabel("첨부 1개")).toBeVisible();

  await card.click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText(ATTACHMENT_NAME)).toBeVisible();
});
