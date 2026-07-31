// 비서 여정 — 임베딩·LLM 필요라 @llm 태그(로컬 Ollama 전용, CI grepInvert 제외).
// 근거 없는 질문은 지어내지 않고 담당자 연결로 폴백해야 한다(절대규칙 1).
import { expect, test } from "@playwright/test";

import { PORTS } from "./fixtures";

const RESIDENT = `http://localhost:${PORTS.resident}`;

test("@llm 근거 없는 질문은 담당자 연결로 폴백한다", async ({ page }) => {
  await page.goto(`${RESIDENT}/assistant`);

  await page.getByLabel("질문 입력").fill("옆 단지 관리소장 개인 휴대폰 번호 알려줘");
  await page.getByRole("button", { name: "질문 보내기" }).click();

  // 폴백 경로: 담당자 연결 배지 + 연락처 안내(환각 아님). 스트림 완료까지 expect 폴링으로 대기.
  // H17 UI 정리로 "담당자 연결" 버튼은 사라졌고 상태 배지가 폴백의 표식이다.
  await expect(page.locator(".confidence-badge--handoff")).toBeVisible({ timeout: 60_000 });
});

test("@llm 비서 응답이 출처 카드 또는 폴백으로 종결된다", async ({ page }) => {
  await page.goto(`${RESIDENT}/assistant`);

  // 추천 질문 칩은 H17 UI 정리로 제거 — 같은 질문을 입력창으로 보낸다.
  await page.getByLabel("질문 입력").fill("분리수거 배출 시간");
  await page.getByRole("button", { name: "질문 보내기" }).click();

  // 근거가 있으면 출처 카드, 없으면 담당자 연결 — 어느 쪽이든 지어내지 않고 종결.
  const citation = page.locator(".citation-card, [data-citation]");
  const handoff = page.locator(".confidence-badge--handoff");
  await expect(citation.or(handoff).first()).toBeVisible({ timeout: 60_000 });
});
