/**
 * 관리자 AI 비서 — 앱별 배선 (ADR-0028 결정 4: 메커니즘은 @liviq/ui, 조립·엔드포인트는 앱).
 * 서버 복원(`fetchLatest`)은 **의도적으로 주지 않는다** — 로그인마다 진입 브리핑이 새로
 * 떠야 하는데(결정 3) 복원이 되면 인사가 안 나온다. 탭 내 연속성은 sessionStorage 로 충분.
 */

import type { AssistantStreamOptions } from "@liviq/ui";
import { API_BASE_URL, apiFetch } from "@/lib/api";

/** 탭 저장 키 — 입주민(`liviq.assistant.thread.*`)과 분리해 대화가 섞이지 않게 한다. */
export const THREAD_STORAGE_KEY = "liviq.admin.assistant.thread.v1";

/** `useAssistantStream` 옵션 — 모듈 상수라 렌더마다 identity 가 바뀌지 않는다. */
export const ADMIN_ASSISTANT_STREAM_OPTIONS: AssistantStreamOptions = {
  askUrl: `${API_BASE_URL}/admin/assistant/ask`,
  apiFetch,
  storageKey: THREAD_STORAGE_KEY,
};
