/**
 * 입주민 AI 비서 — 앱별 배선 (ADR-0028 결정 4: 메커니즘은 @liviq/ui, 조립·엔드포인트는 앱).
 * 여기 남는 것은 이 앱의 엔드포인트·저장 키·복원 경로뿐이다.
 */

import { parseLatestThread, type AssistantStreamOptions, type RestoredThread } from "@liviq/ui";
import { API_BASE_URL, DEV_HEADERS, apiFetch } from "@/lib/dev-context";

/** 탭 저장 키 — 스키마가 바뀌면 뒤 버전을 올려 옛 값을 자연 폐기한다.
 *  v2: AI 메시지에 `steps`(진행 단계) 추가 — H18-3. */
export const THREAD_STORAGE_KEY = "liviq.assistant.thread.v2";

/**
 * GET /assistant/conversations/latest — 본인의 최근 대화(없으면 빈 대화).
 * 응답 형태는 신뢰하지 않는다 — 검증·매핑은 `parseLatestThread`(@liviq/ui) 가 한다.
 */
async function fetchLatest(): Promise<RestoredThread> {
  const response = await apiFetch(`${API_BASE_URL}/assistant/conversations/latest`, {
    headers: DEV_HEADERS,
  });
  if (!response.ok) throw new Error(`대화 복원 실패: ${response.status}`);
  return parseLatestThread(await response.json());
}

/** `useAssistantStream` 옵션 — 모듈 상수라 렌더마다 identity 가 바뀌지 않는다. */
export const ASSISTANT_STREAM_OPTIONS: AssistantStreamOptions = {
  askUrl: `${API_BASE_URL}/assistant/ask`,
  apiFetch,
  storageKey: THREAD_STORAGE_KEY,
  fetchLatest,
};
