// AI 설정(SYS_ADMIN) — /system/ai-config 클라이언트 + 순수 매핑·검증 (H15-1).
// api-types 생성물이 아직 없어 로컬 타입 정의(계약과 1:1) — 백엔드 머지 후 드리프트 게이트가 잡는다.
// 키 원문은 서버가 마스킹해서만 돌려준다 — 웹은 저장·표시 어디에도 원문을 보관하지 않는다.

import { API_BASE_URL, DEV_HEADERS, apiFetch, ensureOk } from "@/lib/api";

/** null = 미지정(env·모델 기본값). "none"은 명시적으로 끄는 별개 값이다. */
export type ReasoningEffort = "none" | "low" | "medium" | "high";

export const REASONING_EFFORTS: readonly ReasoningEffort[] = ["none", "low", "medium", "high"];

/** 스키마 Vector(1024) 고정 — 차원이 다른 임베딩 모델은 저장할 수 없다(docs/03 §4.7). */
export const REQUIRED_EMBEDDING_DIM = 1024;

/** 튜닝 노브 6종 — 화면 렌더·검증·payload 매핑이 모두 이 표를 따른다. */
export type TuningKnob =
  | "chunkMaxTokens"
  | "retrievalTopK"
  | "llmMaxOutputTokens"
  | "llmTimeoutS"
  | "toolConfidence"
  | "answerCacheTtlS";

export interface TuningKnobSpec {
  key: TuningKnob;
  /** 요청·응답 본문의 snake_case 필드명. */
  field: string;
  label: string;
  min: number;
  max: number;
  /** 1이면 정수만 허용. */
  step: number;
  /** env·코드 기본값(폴백) — 도움말 표기용. 서버 기본값과 함께 갱신할 것. */
  fallback: number;
}

/** 청킹 기본값 — 위험 변경 판정(isReindexRequiringChange)에서도 참조한다. */
const CHUNK_MAX_TOKENS_FALLBACK = 400;

export const TUNING_KNOBS: readonly TuningKnobSpec[] = [
  {
    key: "chunkMaxTokens",
    field: "chunk_max_tokens",
    label: "청크 토큰 상한",
    min: 100,
    max: 2000,
    step: 1,
    fallback: CHUNK_MAX_TOKENS_FALLBACK,
  },
  {
    key: "retrievalTopK",
    field: "retrieval_top_k",
    label: "검색 top_k",
    min: 1,
    max: 50,
    step: 1,
    fallback: 16,
  },
  {
    key: "llmMaxOutputTokens",
    field: "llm_max_output_tokens",
    label: "LLM 출력 상한(토큰)",
    min: 64,
    max: 8192,
    step: 1,
    fallback: 1024,
  },
  {
    key: "llmTimeoutS",
    field: "llm_timeout_s",
    label: "LLM timeout(초)",
    min: 5,
    max: 300,
    step: 0.5,
    fallback: 60,
  },
  {
    key: "toolConfidence",
    field: "tool_confidence",
    label: "도구 confidence",
    min: 0,
    max: 1,
    step: 0.05,
    fallback: 0.8,
  },
  {
    key: "answerCacheTtlS",
    field: "answer_cache_ttl_s",
    label: "답변 캐시 TTL(초)",
    min: 0,
    max: 86400,
    step: 1,
    fallback: 3600,
  },
];

/** GET 응답의 노브 값 — 서버가 폴백을 적용해 항상 유효값을 준다. */
export type TuningValues = Record<TuningKnob, number>;
/** 폼 입력 — null = 기본값으로 복귀(서버 컬럼 NULL). */
export type TuningInput = Record<TuningKnob, number | null>;

export interface AiConfig {
  /** DB에 저장된 설정이 있으면 true. false면 env 기본값만으로 동작 중. */
  configured: boolean;
  source: "db" | "env";
  baseUrl: string;
  model: string;
  reasoningEffort: ReasoningEffort | null;
  /** 마스킹된 키(예 "…abcd"). 미설정이면 null. */
  apiKeyMasked: string | null;
  embeddingBaseUrl: string;
  embeddingModel: string;
  embeddingApiKeyMasked: string | null;
  embeddingSource: "db" | "env";
  tuning: TuningValues;
}

export interface EmbeddingInput {
  baseUrl: string;
  model: string;
  /** undefined=기존 키 유지(전송 생략) · ""=키 삭제 · 그 외=교체. */
  apiKey?: string;
}

/** LLM 엔드포인트 4종 — 연결 테스트는 이 부분만 보낸다. */
export interface LlmInput {
  baseUrl: string;
  model: string;
  /** undefined=기존 키 유지(전송 생략) · ""=키 삭제 · 그 외=교체. */
  apiKey?: string;
  reasoningEffort: ReasoningEffort | null;
}

export interface AiConfigInput extends LlmInput {
  embedding: EmbeddingInput;
  tuning: TuningInput;
}

export interface AiTestResult {
  ok: boolean;
  latencyMs: number;
  model: string;
  error: string | null;
}

export interface EmbeddingTestResult extends AiTestResult {
  /** 실측 임베딩 차원. REQUIRED_EMBEDDING_DIM 이 아니면 저장이 422로 거부된다. */
  dimensions: number;
}

/** 재색인 enqueue 결과 — 실제 처리는 ai-worker 가 큐에서 소비한다. */
export interface ReindexResult {
  enqueuedDocuments: number;
  enqueuedNotices: number;
}

/** documents.index_status 어휘 그대로의 집계(api ReindexStatusOut). */
export interface ReindexStatus {
  pending: number;
  indexing: number;
  indexed: number;
  failed: number;
  total: number;
}

interface RawAiConfig {
  configured: boolean;
  source: string;
  base_url: string;
  model: string;
  reasoning_effort?: string | null;
  api_key_masked?: string | null;
  embedding_base_url?: string | null;
  embedding_model?: string | null;
  embedding_api_key_masked?: string | null;
  embedding_source?: string | null;
  [knob: string]: unknown;
}

interface RawAiTestResult {
  ok: boolean;
  latency_ms: number;
  model: string;
  error?: string | null;
  dimensions?: number | null;
}

function toEffort(value: string | null | undefined): ReasoningEffort | null {
  return REASONING_EFFORTS.includes(value as ReasoningEffort) ? (value as ReasoningEffort) : null;
}

/** 노브 값 매핑 — 응답에 없거나 숫자가 아니면 표의 폴백을 쓴다(화면이 빈 칸이 되지 않게). */
function toTuningValues(raw: RawAiConfig): TuningValues {
  const values = {} as TuningValues;
  for (const spec of TUNING_KNOBS) {
    const value = raw[spec.field];
    values[spec.key] = typeof value === "number" && Number.isFinite(value) ? value : spec.fallback;
  }
  return values;
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
    embeddingBaseUrl: raw.embedding_base_url ?? "",
    embeddingModel: raw.embedding_model ?? "",
    embeddingApiKeyMasked: raw.embedding_api_key_masked ?? null,
    embeddingSource: raw.embedding_source === "db" ? "db" : "env",
    tuning: toTuningValues(raw),
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

/** 임베딩 연결 테스트 응답 — 차원 누락은 0(=검증 실패로 읽히는 값)으로 접는다. */
export function toEmbeddingTestResult(raw: RawAiTestResult): EmbeddingTestResult {
  return { ...toAiTestResult(raw), dimensions: raw.dimensions ?? 0 };
}

/**
 * AiConfigInput → 요청 본문. api_key 는 undefined면 키 자체를 생략(기존 유지),
 * 빈 문자열이면 ""로 보내 삭제를 요청한다. 두 경우를 섞으면 키가 지워진다 — 구분이 계약의 핵심.
 */
export function buildAiConfigPayload(input: LlmInput): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    base_url: input.baseUrl.trim(),
    model: input.model.trim(),
    reasoning_effort: input.reasoningEffort,
  };
  if (input.apiKey !== undefined) payload.api_key = input.apiKey;
  return payload;
}

/** 임베딩 3종만 담은 본문 — test-embedding 전용(LLM 필드를 섞지 않는다). */
export function buildEmbeddingPayload(input: EmbeddingInput): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    embedding_base_url: input.baseUrl.trim(),
    embedding_model: input.model.trim(),
  };
  if (input.apiKey !== undefined) payload.embedding_api_key = input.apiKey;
  return payload;
}

/** PUT 본문 — LLM·임베딩·노브 전체. 노브 null 은 명시해 보낸다(기본값 복귀 요청). */
export function buildSavePayload(input: AiConfigInput): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    ...buildAiConfigPayload(input),
    ...buildEmbeddingPayload(input.embedding),
  };
  for (const spec of TUNING_KNOBS) {
    payload[spec.field] = input.tuning[spec.key];
  }
  return payload;
}

/** 노브 입력 문자열 → 값. 빈 값은 null(기본값 사용), 숫자가 아니면 NaN(검증에서 걸린다). */
export function parseKnob(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return Number(trimmed);
}

/** 노브 범위 검증 — null(기본값)은 통과. 실패 시 사용자 안내 메시지. */
export function validateKnob(spec: TuningKnobSpec, value: number | null): string | null {
  if (value === null) return null;
  if (!Number.isFinite(value)) return "숫자를 입력하세요.";
  if (spec.step === 1 && !Number.isInteger(value)) return "정수를 입력하세요.";
  if (value < spec.min || value > spec.max) {
    return `${spec.min}~${spec.max} 범위로 입력하세요.`;
  }
  return null;
}

/** 노브 전체 검증 — 실패한 노브만 담은 맵(빈 객체면 통과). */
export function validateTuning(input: TuningInput): Partial<Record<TuningKnob, string>> {
  const errors: Partial<Record<TuningKnob, string>> = {};
  for (const spec of TUNING_KNOBS) {
    const message = validateKnob(spec, input[spec.key]);
    if (message) errors[spec.key] = message;
  }
  return errors;
}

/**
 * 저장 전 경고 대상인지 — 임베딩 3종·chunk_max_tokens 변경은 기존 색인과 불일치를 만든다
 * (docs/03 §4.7 위험 노브 규율). 반영은 재색인으로 완성된다.
 */
export function isReindexRequiringChange(config: AiConfig, input: AiConfigInput): boolean {
  const chunk = input.tuning.chunkMaxTokens ?? CHUNK_MAX_TOKENS_FALLBACK;
  return (
    input.embedding.baseUrl !== config.embeddingBaseUrl ||
    input.embedding.model !== config.embeddingModel ||
    input.embedding.apiKey !== undefined ||
    chunk !== config.tuning.chunkMaxTokens
  );
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

/**
 * AI 설정 저장 — DB 설정이 env 기본값을 덮는다. 응답은 저장 후 현재 상태.
 * 임베딩 차원이 REQUIRED_EMBEDDING_DIM 과 다르면 422(ApiError.message 에 실측 차원)로 거부된다.
 */
export async function saveAiConfig(input: AiConfigInput): Promise<AiConfig> {
  const response = await apiFetch(CONFIG_URL, {
    method: "PUT",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(buildSavePayload(input)),
  });
  await ensureOk(response);
  return toAiConfig(await response.json());
}

/** 연결 테스트 — 저장하지 않고 폼 값으로만 호출한다(실패도 200 + ok:false). */
export async function testAiConfig(input: LlmInput): Promise<AiTestResult> {
  const response = await apiFetch(`${CONFIG_URL}/test`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(buildAiConfigPayload(input)),
  });
  await ensureOk(response);
  return toAiTestResult(await response.json());
}

/** 임베딩 연결 테스트 — 실제 임베딩 1회 호출로 차원을 실측한다(실패도 200 + ok:false). */
export async function testEmbeddingConfig(input: EmbeddingInput): Promise<EmbeddingTestResult> {
  const response = await apiFetch(`${CONFIG_URL}/test-embedding`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(buildEmbeddingPayload(input)),
  });
  await ensureOk(response);
  return toEmbeddingTestResult(await response.json());
}

/** 전 단지 문서·공지 재인제스트 enqueue — 본문 없음. 실제 처리는 ai-worker. */
export async function startReindex(): Promise<ReindexResult> {
  const response = await apiFetch(`${CONFIG_URL}/reindex`, {
    method: "POST",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return {
    enqueuedDocuments: body.enqueued_documents ?? 0,
    enqueuedNotices: body.enqueued_notices ?? 0,
  };
}

/** 색인 진행 현황. */
export async function getReindexStatus(): Promise<ReindexStatus> {
  const response = await apiFetch(`${CONFIG_URL}/reindex-status`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return {
    pending: body.pending ?? 0,
    indexing: body.indexing ?? 0,
    indexed: body.indexed ?? 0,
    failed: body.failed ?? 0,
    total: body.total ?? 0,
  };
}

/** 남은 작업이 있으면 진행 중 — 폴링 조건. */
export function isReindexRunning(status: ReindexStatus): boolean {
  return status.pending > 0 || status.indexing > 0;
}
