/**
 * 관리자 AI 비서 — 앱별 배선 (ADR-0028 결정 4: 메커니즘은 @liviq/ui, 조립·엔드포인트는 앱).
 * 복원은 **당일(KST)** 만이다(결정 2 개정, H20-3) — 탭 저장 키에 날짜를 붙이고, 서버도
 * 당일 대화만 준다. 날이 바뀌면 둘 다 비어 새 대화 + 진입 브리핑으로 시작한다.
 */

import { parseLatestThread, type AssistantStreamOptions, type RestoredThread } from "@liviq/ui";
import { API_BASE_URL, apiFetch } from "@/lib/api";
import { kstDateKey } from "./briefing";

/**
 * 탭 저장 키 — 입주민(`liviq.assistant.thread.*`)과 분리해 대화가 섞이지 않게 한다.
 * KST 날짜 접미는 **모듈 로드 시 1회** 계산된다: 탭을 켠 채 자정을 넘겨도 그 탭에서는
 * 옛 키를 계속 쓰고(대화 유지), 새로고침·재진입부터 새 키 + 브리핑이 된다.
 */
export const THREAD_STORAGE_KEY = `liviq.admin.assistant.thread.v1.${kstDateKey(new Date())}`;

/**
 * GET /admin/assistant/conversations/latest — 본인의 **당일** 관리자 대화(없으면 빈 대화).
 * 응답 형태는 신뢰하지 않는다 — 검증·매핑은 `parseLatestThread`(@liviq/ui) 가 한다.
 * dev 헤더는 `apiFetch` 가 붙인다(web-resident 와 달리 호출부가 실을 필요 없음).
 */
async function fetchLatest(): Promise<RestoredThread> {
  const response = await apiFetch(`${API_BASE_URL}/admin/assistant/conversations/latest`);
  if (!response.ok) throw new Error(`대화 복원 실패: ${response.status}`);
  return parseLatestThread(await response.json());
}

/** `useAssistantStream` 옵션 — 모듈 상수라 렌더마다 identity 가 바뀌지 않는다. */
export const ADMIN_ASSISTANT_STREAM_OPTIONS: AssistantStreamOptions = {
  askUrl: `${API_BASE_URL}/admin/assistant/ask`,
  apiFetch,
  storageKey: THREAD_STORAGE_KEY,
  fetchLatest,
};
