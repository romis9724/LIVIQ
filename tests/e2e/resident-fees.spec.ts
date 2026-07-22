// 입주민 관리비 여정 — 당월 확정 데이터 합계·항목·전월 대비 렌더 확인(표시 전용).
import { expect, test } from "@playwright/test";

import { FEE_BREAKDOWN, FEE_CURRENT_TOTAL, PORTS } from "./fixtures";

const RESIDENT = `http://localhost:${PORTS.resident}`;

/** FeesView.formatWon 과 동일 표기. */
function won(n: number): string {
  return `${n.toLocaleString("ko-KR")}원`;
}

test("당월 확정 관리비의 합계·항목·전월 대비가 표시된다", async ({ page }) => {
  await page.goto(`${RESIDENT}/fees`);

  // 당월 합계(월 카드·항목 합계에 중복 노출되므로 first).
  await expect(page.getByText(won(FEE_CURRENT_TOTAL)).first()).toBeVisible();

  // 항목별 내역 — 시드 breakdown 트리 항목명이 모두 렌더.
  for (const row of FEE_BREAKDOWN) {
    await expect(page.getByText(row.name).first()).toBeVisible();
  }

  // 당월 > 전월이라 전월 대비 배지 노출(월 카드 델타 + 비교 섹션 제목 중복 → first).
  await expect(page.getByText("전월 대비").first()).toBeVisible();
});
