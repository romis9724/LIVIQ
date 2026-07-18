// 가입 여정의 AI 이용 마무리(H6-4, @llm) — 임베딩·LLM 필요라 로컬 Ollama 전용(CI grepInvert 제외).
//
// 승인된 입주민이 비서에게 질의하면 근거(출처 카드) 또는 담당자 연결(폴백)로 종결한다(절대규칙 1).
// 여정의 신규 가입자와 시드 활성 사용자는 모두 "승인된 활성 입주민"으로 동치이므로, 결정론 스펙과의
// 취약한 파일 간 상태 공유 대신 기본 storageState(승인된 활성 입주민)로 AI 종결만 검증한다.
import { expect, test } from "@playwright/test";

import { PORTS } from "./fixtures";

const RESIDENT = `http://localhost:${PORTS.resident}`;

test("@llm 승인된 입주민의 비서 질의가 출처 카드 또는 폴백으로 종결된다", async ({
  page,
}) => {
  await page.goto(`${RESIDENT}/assistant`);

  await page
    .getByLabel("질문 입력")
    .fill("우리 단지 관리비는 어떻게 확인하나요?");
  await page.getByRole("button", { name: "질문 보내기" }).click();

  // 지어내지 않고 종결: 근거 있으면 출처 카드, 없으면 담당자 연결.
  const citation = page.locator(".citation-card, [data-citation]");
  const handoff = page.getByRole("button", { name: "담당자 연결" });
  await expect(citation.or(handoff).first()).toBeVisible({ timeout: 60_000 });
});
