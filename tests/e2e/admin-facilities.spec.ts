// 관리자 시설 CRUD 여정 — 설비 등록→선택→장애 기록→이력 반영(결정론·CI 게이트).
// dev 헤더 컨텍스트는 MANAGER 역할을 포함해 시설 쓰기(create/incident)를 통과한다.
import { expect, test } from "@playwright/test";

import { PORTS } from "./fixtures";

const ADMIN = `http://localhost:${PORTS.admin}`;

test("설비 등록 후 장애를 기록하면 상세 이력에 반영된다", async ({ page }) => {
  const name = `E2E 승강기 ${Date.now()}`;
  const symptom = "운행 중 덜컹 소음이 발생합니다.";

  await page.goto(`${ADMIN}/facilities`);

  // 설비 등록 다이얼로그.
  await page.getByRole("button", { name: "설비 등록" }).click();
  const dialog = page.getByRole("dialog", { name: "설비 등록" });
  await dialog.getByLabel("설비 이름").fill(name);
  await dialog.getByRole("button", { name: "등록" }).click();

  // 등록 확인 + 목록 카드 노출.
  await expect(page.getByText("설비를 등록했습니다.")).toBeVisible();
  const card = page.locator(".fac-card").filter({ hasText: name });
  await expect(card).toBeVisible();

  // 선택 → 상세 진입.
  await card.click();
  await expect(page.locator(".fac-detail__name").filter({ hasText: name })).toBeVisible();

  // 장애 기록.
  await page.getByRole("button", { name: "장애 기록" }).click();
  const incidentDialog = page.getByRole("dialog", { name: "장애 기록" });
  await incidentDialog.getByLabel("증상").fill(symptom);
  await incidentDialog.getByRole("button", { name: "기록" }).click();

  // 기록 확인 + 장애 이력에 반영.
  await expect(page.getByText("장애를 기록했습니다.")).toBeVisible();
  await expect(page.locator(".fac-history__primary").filter({ hasText: symptom })).toBeVisible();
});
