// 관리자 검수 큐 여정 — needs_review 메시지 표시→승인→대기 목록에서 사라짐.
import { expect, test } from "@playwright/test";

import { PORTS, REVIEW } from "./fixtures";

const ADMIN = `http://localhost:${PORTS.admin}`;

test("검수 대기 답변을 승인하면 대기 목록에서 제거된다", async ({ page }) => {
  await page.goto(`${ADMIN}/review-queue`);

  // 시드된 저신뢰 답변이 대기 목록에 노출.
  const question = page.getByRole("heading", { name: REVIEW.question });
  await expect(question).toBeVisible();

  // 승인 처리 → 카드가 목록에서 사라짐(사후 검수, 회수 없음).
  await page.getByRole("button", { name: "승인" }).click();
  await expect(page.getByText("승인 처리했습니다.", { exact: false })).toBeVisible();
  await expect(question).toHaveCount(0);
});
