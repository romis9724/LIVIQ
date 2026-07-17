// 입주민 공지 여정 — 목록에 시드 공지 표시→상세 진입 본문 확인.
import { expect, test } from "@playwright/test";

import { NOTICE1, PORTS } from "./fixtures";

const RESIDENT = `http://localhost:${PORTS.resident}`;

test("발행된 공지가 목록에 뜨고 상세에서 본문을 볼 수 있다", async ({ page }) => {
  await page.goto(`${RESIDENT}/notices`);

  const card = page.locator(".notice-card").filter({ hasText: NOTICE1.title });
  await expect(card).toBeVisible();

  await card.click();
  await expect(page.getByRole("heading", { name: NOTICE1.title })).toBeVisible();
  await expect(page.getByText(NOTICE1.body)).toBeVisible();
});
