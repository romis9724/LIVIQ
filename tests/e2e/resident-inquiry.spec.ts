// 입주민 민원 여정 — 접수 폼 작성→제출→목록 표시→상세 타임라인 접수 이벤트.
import { expect, test } from "@playwright/test";

import { PORTS } from "./fixtures";

const RESIDENT = `http://localhost:${PORTS.resident}`;

test("입주민이 민원을 접수하면 목록·상세 타임라인에 반영된다", async ({ page }) => {
  const title = `E2E 엘리베이터 소음 ${Date.now()}`;

  await page.goto(`${RESIDENT}/inquiries`);

  // 접수 탭으로 전환 후 폼 작성.
  await page.getByRole("tab", { name: "접수하기" }).click();
  await page.getByLabel("제목").fill(title);
  await page.getByLabel("상세 내용").fill("복도 엘리베이터에서 큰 소음이 납니다. 점검 부탁드립니다.");
  await page.getByRole("button", { name: "접수하기" }).click();

  // 접수 확인 토스트 + 목록에 새 민원 노출.
  await expect(page.getByText("민원을 접수했습니다.")).toBeVisible();
  const card = page.locator(".inq-card").filter({ hasText: title });
  await expect(card).toBeVisible();

  // 상세 진입 → 타임라인에 접수 이벤트.
  await card.click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("민원 접수됨")).toBeVisible();
});
