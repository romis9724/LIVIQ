// AI 설정(SYS_ADMIN) — /system/ai-config 클라이언트 + 순수 매핑·검증 (H15-1).
// api-types 생성물이 아직 없어 로컬 타입 정의(계약과 1:1) — 백엔드 머지 후 드리프트 게이트가 잡는다.
// 키 원문은 서버가 마스킹해서만 돌려준다 — 웹은 저장·표시 어디에도 원문을 보관하지 않는다.

import { API_BASE_URL, DEV_HEADERS, apiFetch, ensureOk } from "@/lib/api";

/** null = 미지정(env·모델 기본값). "none"은 명시적으로 끄는 별개 값이다. */
export type ReasoningEffort = "none" | "low" | "medium" | "high";

export const REASONING_EFFORTS: readonly ReasoningEffort[] = ["none", "low", "medium", "high"];

export interface AiConfig {
  /** DB에 저장된 설정이 있으면 true. false면 env 기본값만으로 동작 중. */
  configured: boolean;
  source: "db" | "env";
  baseUrl: string;
  model: string;
  reasoningEffort: ReasoningEffort | null;
  /** 마스킹된 키(예 "…abcd"). 미설정이면 null. */
  apiKeyMasked: string | null;
}

export interface AiConfigInput {
  baseUrl: string;
  model: string;
  /** undefined=기존 키 유지(전송 생략) · ""=키 삭제 · 그 외=교체. */
  apiKey?: string;
  reasoningEffort: ReasoningEffort | null;
}

export interface AiTestResult {
  ok: boolean;
  latencyMs: number;
  model: string;
  error: string | null;
}

interface RawAiConfig {
  configured: boolean;
  source: string;
  base_url: string;
  model: string;
  reasoning_effort?: string | null;
  api_key_masked?: string | null;
}

interface RawAiTestResult {
  ok: boolean;
  latency_ms: number;
  model: string;
  error?: string | null;
}

function toEffort(value: string | null | undefined): ReasoningEffort | null {
  return REASONING_EFFORTS.includes(value as ReasoningEffort) ? (value as ReasoningEffort) : null;
}

/** api 응답(snake_case) → AiConfig. 알 수 없는 effort·source는 안전한 기본값으로 접는다. */
export function toAiConfig(raw: RawAiConfig): AiConfig {
  return {
    configured: Boolean(raw.configured),
    source: raw.source === "db" ? "db" : "env",
    baseUrl: raw.base_url,
    model: raw.model,
    reasoningEffort: toEffort(raw.reasoning_effort),
    apiKeyMasked: raw.api_key_masked ?? null,
  };
}

export function toAiTestResult(raw: RawAiTestResult): AiTestResult {
  return {
    ok: Boolean(raw.ok),
    latencyMs: raw.latency_ms,
    model: raw.model,
    error: raw.error ?? null,
  };
}

/**
 * AiConfigInput → 요청 본문. api_key 는 undefined면 키 자체를 생략(기존 유지),
 * 빈 문자열이면 ""로 보내 삭제를 요청한다. 두 경우를 섞으면 키가 지워진다 — 구분이 계약의 핵심.
 */
export function buildAiConfigPayload(input: AiConfigInput): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    base_url: input.baseUrl.trim(),
    model: input.model.trim(),
    reasoning_effort: input.reasoningEffort,
  };
  if (input.apiKey !== undefined) payload.api_key = input.apiKey;
  return payload;
}

/** base URL 검증 — http(s) 절대 URL만. 통과 시 null, 실패 시 사용자 안내 메시지. */
export function validateBaseUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return "base URL을 입력하세요.";
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return "URL 형식이 올바르지 않습니다. (예: http://localhost:11434/v1)";
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return "http 또는 https 주소만 사용할 수 있습니다.";
  }
  return null;
}

/** 모델명 검증 — 공백만 아니면 통과(허용 목록은 프로바이더가 정한다). */
export function validateModel(value: string): string | null {
  return value.trim() ? null : "모델명을 입력하세요.";
}

const CONFIG_URL = `${API_BASE_URL}/system/ai-config`;

/** 현재 AI 설정 조회(SYS_ADMIN). 403=권한 없음. */
export async function getAiConfig(): Promise<AiConfig> {
  const response = await apiFetch(CONFIG_URL, { headers: DEV_HEADERS });
  await ensureOk(response);
  return toAiConfig(await response.json());
}

/** AI 설정 저장 — DB 설정이 env 기본값을 덮는다. 응답은 저장 후 현재 상태. */
export async function saveAiConfig(input: AiConfigInput): Promise<AiConfig> {
  const response = await apiFetch(CONFIG_URL, {
    method: "PUT",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(buildAiConfigPayload(input)),
  });
  await ensureOk(response);
  return toAiConfig(await response.json());
}

/** 연결 테스트 — 저장하지 않고 폼 값으로만 호출한다(실패도 200 + ok:false). */
export async function testAiConfig(input: AiConfigInput): Promise<AiTestResult> {
  const response = await apiFetch(`${CONFIG_URL}/test`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(buildAiConfigPayload(input)),
  });
  await ensureOk(response);
  return toAiTestResult(await response.json());
}
