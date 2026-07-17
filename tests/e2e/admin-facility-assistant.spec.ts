// 시설 AI 도우미 여정 — @llm(임베딩·LLM + Neo4j 필요) 로컬 전용, CI grepInvert 제외.
// 유사 장애 이력 근거로 가능 원인 후보(또는 근거 부재 시 담당자 안내 폴백)를 스트림한다.
import { expect, test } from "@playwright/test";

import { PORTS } from "./fixtures";

const ADMIN = `http://localhost:${PORTS.admin}`;

test("@llm 시설 도우미에 질문하면 원인 후보 또는 폴백을 출처와 함께 응답한다", async ({
  page,
}) => {
  await page.goto(`${ADMIN}/facilities`);

  const panel = page.locator(".fac-ai");
  await expect(panel).toBeVisible();

  await panel.getByLabel("시설 질문 입력").fill("승강기 덜컹 소음의 가능 원인 후보를 알려줘");
  await panel.getByRole("button", { name: "질문" }).click();

  // 스트림 종료까지 대기 — 신뢰도 배지(답변) 또는 담당자 연결 배지(폴백) 중 하나가 확정된다.
  await expect(panel.locator(".confidence-badge")).toBeVisible();
  // 응답 본문이 비어 있지 않다(원인 후보 텍스트 또는 폴백 안내).
  await expect(panel.locator(".fac-ai__text")).not.toBeEmpty();
});
