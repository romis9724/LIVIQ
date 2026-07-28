import { afterEach, describe, expect, it, vi } from "vitest";

import {
  REQUIRED_EMBEDDING_DIM,
  TUNING_KNOBS,
  buildAiConfigPayload,
  buildEmbeddingPayload,
  buildSavePayload,
  getReindexStatus,
  isReindexRequiringChange,
  isReindexRunning,
  parseKnob,
  startReindex,
  testEmbeddingConfig,
  toAiConfig,
  toAiTestResult,
  toEmbeddingTestResult,
  validateBaseUrl,
  validateKnob,
  validateModel,
  validateTuning,
  type AiConfig,
  type AiConfigInput,
  type LlmInput,
  type TuningValues,
  type TuningKnobSpec,
} from "./data";

function makeInput(over: Partial<LlmInput> = {}): LlmInput {
  return {
    baseUrl: "http://localhost:11434/v1",
    model: "llama3.1:8b",
    reasoningEffort: null,
    ...over,
  };
}

const RAW_KNOBS = {
  chunk_max_tokens: 400,
  retrieval_top_k: 8,
  llm_max_output_tokens: 1024,
  llm_timeout_s: 60,
  tool_confidence: 0.8,
  answer_cache_ttl_s: 3600,
};

const TUNING: TuningValues = {
  chunkMaxTokens: 400,
  retrievalTopK: 8,
  llmMaxOutputTokens: 1024,
  llmTimeoutS: 60,
  toolConfidence: 0.8,
  answerCacheTtlS: 3600,
};

function makeConfig(over: Partial<AiConfig> = {}): AiConfig {
  return {
    configured: true,
    source: "db",
    baseUrl: "http://localhost:11434/v1",
    model: "llama3.1:8b",
    reasoningEffort: null,
    apiKeyMasked: null,
    embeddingBaseUrl: "http://localhost:11434/v1",
    embeddingModel: "bge-m3",
    embeddingApiKeyMasked: null,
    embeddingSource: "db",
    tuning: { ...TUNING },
    ...over,
  };
}

function makeSaveInput(over: Partial<AiConfigInput> = {}): AiConfigInput {
  return {
    ...makeInput(),
    embedding: { baseUrl: "http://localhost:11434/v1", model: "bge-m3" },
    tuning: { ...TUNING },
    ...over,
  };
}

function knobSpec(field: string): TuningKnobSpec {
  const spec = TUNING_KNOBS.find((candidate) => candidate.field === field);
  if (!spec) throw new Error(`unknown knob: ${field}`);
  return spec;
}

/** apiFetch 는 global fetch 를 쓴다 — 응답은 ok·status·json 만 소비하므로 최소 스텁으로 충분하다. */
function stubFetch(body: unknown, ok = true, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({ ok, status, json: async () => body });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("toAiConfig (GET 응답 매핑)", () => {
  it("snake_case 응답을 camelCase 설정으로 옮긴다", () => {
    const config = toAiConfig({
      configured: true,
      source: "db",
      base_url: "https://llm.example.com/v1",
      model: "llama3.1:8b",
      reasoning_effort: "low",
      api_key_masked: "…abcd",
      embedding_base_url: "https://embed.example.com/v1",
      embedding_model: "bge-m3",
      embedding_api_key_masked: "…wxyz",
      embedding_source: "db",
      ...RAW_KNOBS,
    });

    expect(config).toEqual({
      configured: true,
      source: "db",
      baseUrl: "https://llm.example.com/v1",
      model: "llama3.1:8b",
      reasoningEffort: "low",
      apiKeyMasked: "…abcd",
      embeddingBaseUrl: "https://embed.example.com/v1",
      embeddingModel: "bge-m3",
      embeddingApiKeyMasked: "…wxyz",
      embeddingSource: "db",
      tuning: TUNING,
    });
  });

  it("노브 값을 camelCase 키로 옮긴다", () => {
    const config = toAiConfig({
      configured: true,
      source: "db",
      base_url: "http://x/v1",
      model: "m",
      ...RAW_KNOBS,
      retrieval_top_k: 12,
      tool_confidence: 0.55,
    });

    expect(config.tuning.retrievalTopK).toBe(12);
    expect(config.tuning.toolConfidence).toBe(0.55);
  });

  it("임베딩 필드·노브가 없으면 빈 값·표의 기본값으로 접는다", () => {
    const config = toAiConfig({
      configured: false,
      source: "env",
      base_url: "http://x/v1",
      model: "m",
    });

    expect(config.embeddingBaseUrl).toBe("");
    expect(config.embeddingModel).toBe("");
    expect(config.embeddingApiKeyMasked).toBeNull();
    expect(config.embeddingSource).toBe("env");
    expect(config.tuning).toEqual(TUNING);
  });

  it("effort·마스킹 키 누락은 null로 접는다", () => {
    const config = toAiConfig({
      configured: false,
      source: "env",
      base_url: "http://localhost:11434/v1",
      model: "llama3.1:8b",
    });

    expect(config.reasoningEffort).toBeNull();
    expect(config.apiKeyMasked).toBeNull();
    expect(config.source).toBe("env");
  });

  it("알 수 없는 effort·source 값은 안전한 기본값으로 접는다", () => {
    const config = toAiConfig({
      configured: true,
      source: "somewhere",
      base_url: "http://x/v1",
      model: "m",
      reasoning_effort: "extreme",
    });

    expect(config.reasoningEffort).toBeNull();
    expect(config.source).toBe("env");
  });
});

describe("buildAiConfigPayload (PUT·test 본문)", () => {
  it("base_url·model을 트림해 담고 effort는 null도 명시한다", () => {
    expect(buildAiConfigPayload(makeInput({ baseUrl: "  http://x/v1  ", model: " m " }))).toEqual({
      base_url: "http://x/v1",
      model: "m",
      reasoning_effort: null,
    });
  });

  it("apiKey 미지정(undefined)이면 api_key 키 자체를 생략한다 — 기존 키 유지", () => {
    const payload = buildAiConfigPayload(makeInput({ apiKey: undefined }));
    expect("api_key" in payload).toBe(false);
  });

  it("apiKey 빈 문자열이면 api_key:\"\"를 보낸다 — 키 삭제", () => {
    expect(buildAiConfigPayload(makeInput({ apiKey: "" })).api_key).toBe("");
  });

  it("apiKey가 있으면 원문 그대로 보낸다 — 교체", () => {
    expect(buildAiConfigPayload(makeInput({ apiKey: "sk-new" })).api_key).toBe("sk-new");
  });

  it("effort를 지정하면 그대로 담는다", () => {
    expect(buildAiConfigPayload(makeInput({ reasoningEffort: "high" })).reasoning_effort).toBe(
      "high",
    );
  });
});

describe("toAiTestResult (연결 테스트 응답)", () => {
  it("성공 응답을 매핑한다", () => {
    expect(toAiTestResult({ ok: true, latency_ms: 412, model: "llama3.1:8b", error: null })).toEqual(
      { ok: true, latencyMs: 412, model: "llama3.1:8b", error: null },
    );
  });

  it("실패 응답의 error 메시지를 보존한다", () => {
    const result = toAiTestResult({
      ok: false,
      latency_ms: 30,
      model: "llama3.1:8b",
      error: "connection refused",
    });
    expect(result.ok).toBe(false);
    expect(result.error).toBe("connection refused");
  });

  it("error 누락은 null로 접는다", () => {
    expect(toAiTestResult({ ok: true, latency_ms: 1, model: "m" }).error).toBeNull();
  });
});

describe("validateBaseUrl", () => {
  it("http·https 절대 URL은 통과한다", () => {
    expect(validateBaseUrl("http://localhost:11434/v1")).toBeNull();
    expect(validateBaseUrl(" https://llm.example.com/v1 ")).toBeNull();
  });

  it("빈 값은 필수 안내를 돌려준다", () => {
    expect(validateBaseUrl("   ")).toBe("base URL을 입력하세요.");
  });

  it("URL로 파싱되지 않으면 형식 안내를 돌려준다", () => {
    expect(validateBaseUrl("그냥 텍스트")).toContain("URL 형식");
  });

  it("http(s)가 아닌 스킴은 거부한다 (스킴 없는 host:port 포함)", () => {
    expect(validateBaseUrl("ftp://example.com")).toContain("http");
    expect(validateBaseUrl("localhost:11434")).toContain("http");
  });
});

describe("validateModel", () => {
  it("값이 있으면 통과, 공백뿐이면 안내를 돌려준다", () => {
    expect(validateModel("llama3.1:8b")).toBeNull();
    expect(validateModel("  ")).toBe("모델명을 입력하세요.");
  });
});

describe("buildEmbeddingPayload (test-embedding 본문)", () => {
  it("임베딩 3종만 담고 트림한다 — LLM 필드는 섞지 않는다", () => {
    expect(
      buildEmbeddingPayload({ baseUrl: "  http://x/v1 ", model: " bge-m3 " }),
    ).toEqual({ embedding_base_url: "http://x/v1", embedding_model: "bge-m3" });
  });

  it("apiKey 미지정이면 키 자체를 생략하고, 빈 문자열이면 삭제를 보낸다", () => {
    expect("embedding_api_key" in buildEmbeddingPayload({ baseUrl: "http://x", model: "m" })).toBe(
      false,
    );
    expect(
      buildEmbeddingPayload({ baseUrl: "http://x", model: "m", apiKey: "" }).embedding_api_key,
    ).toBe("");
    expect(
      buildEmbeddingPayload({ baseUrl: "http://x", model: "m", apiKey: "sk-e" }).embedding_api_key,
    ).toBe("sk-e");
  });
});

describe("buildSavePayload (PUT 본문)", () => {
  it("LLM·임베딩·노브 6종을 한 본문에 담는다", () => {
    const payload = buildSavePayload(makeSaveInput());

    expect(payload.base_url).toBe("http://localhost:11434/v1");
    expect(payload.embedding_model).toBe("bge-m3");
    for (const spec of TUNING_KNOBS) {
      expect(payload[spec.field]).toBe(TUNING[spec.key]);
    }
  });

  it("노브 null 은 명시해 보낸다 — 기본값 복귀 요청", () => {
    const payload = buildSavePayload(
      makeSaveInput({ tuning: { ...TUNING, retrievalTopK: null } }),
    );

    expect("retrieval_top_k" in payload).toBe(true);
    expect(payload.retrieval_top_k).toBeNull();
  });
});

describe("parseKnob", () => {
  it("빈 값은 null(기본값 사용), 숫자는 숫자로 읽는다", () => {
    expect(parseKnob("")).toBeNull();
    expect(parseKnob("   ")).toBeNull();
    expect(parseKnob(" 12 ")).toBe(12);
    expect(parseKnob("0.35")).toBe(0.35);
    expect(parseKnob("0")).toBe(0);
  });

  it("숫자가 아니면 NaN 을 돌려준다 — 검증에서 걸리게", () => {
    expect(Number.isNaN(parseKnob("여덟") as number)).toBe(true);
  });
});

describe("validateKnob", () => {
  const topK = knobSpec("retrieval_top_k");
  const confidence = knobSpec("tool_confidence");

  it("null(기본값)과 범위 안의 값은 통과한다", () => {
    expect(validateKnob(topK, null)).toBeNull();
    expect(validateKnob(topK, 1)).toBeNull();
    expect(validateKnob(topK, 50)).toBeNull();
    expect(validateKnob(confidence, 0)).toBeNull();
    expect(validateKnob(confidence, 0.85)).toBeNull();
  });

  it("범위를 벗어나면 범위 안내를 돌려준다", () => {
    expect(validateKnob(topK, 0)).toBe("1~50 범위로 입력하세요.");
    expect(validateKnob(topK, 51)).toBe("1~50 범위로 입력하세요.");
    expect(validateKnob(confidence, 1.5)).toBe("0~1 범위로 입력하세요.");
  });

  it("숫자가 아니거나 정수 노브에 소수를 넣으면 형식 안내를 돌려준다", () => {
    expect(validateKnob(topK, Number.NaN)).toBe("숫자를 입력하세요.");
    expect(validateKnob(topK, 8.5)).toBe("정수를 입력하세요.");
    expect(validateKnob(confidence, 0.35)).toBeNull(); // 소수 노브는 허용
  });
});

describe("validateTuning", () => {
  it("전부 유효하면 빈 객체를 돌려준다", () => {
    expect(validateTuning({ ...TUNING })).toEqual({});
  });

  it("실패한 노브만 담는다", () => {
    const errors = validateTuning({ ...TUNING, retrievalTopK: 99, chunkMaxTokens: 50 });

    expect(Object.keys(errors).sort()).toEqual(["chunkMaxTokens", "retrievalTopK"]);
    expect(errors.retrievalTopK).toContain("1~50");
  });
});

describe("isReindexRequiringChange (위험 변경 판정)", () => {
  const config = makeConfig();

  it("임베딩·청킹이 그대로면 false", () => {
    expect(isReindexRequiringChange(config, makeSaveInput())).toBe(false);
  });

  it("임베딩 base URL·모델·키 변경은 true", () => {
    const changedUrl = makeSaveInput({
      embedding: { baseUrl: "http://other/v1", model: "bge-m3" },
    });
    const changedModel = makeSaveInput({
      embedding: { baseUrl: config.embeddingBaseUrl, model: "e5-large" },
    });
    const changedKey = makeSaveInput({
      embedding: { baseUrl: config.embeddingBaseUrl, model: "bge-m3", apiKey: "sk-e" },
    });

    expect(isReindexRequiringChange(config, changedUrl)).toBe(true);
    expect(isReindexRequiringChange(config, changedModel)).toBe(true);
    expect(isReindexRequiringChange(config, changedKey)).toBe(true);
  });

  it("chunk_max_tokens 변경은 true, 기본값 복귀(null)가 현재 값과 같으면 false", () => {
    expect(
      isReindexRequiringChange(config, makeSaveInput({ tuning: { ...TUNING, chunkMaxTokens: 800 } })),
    ).toBe(true);
    expect(
      isReindexRequiringChange(config, makeSaveInput({ tuning: { ...TUNING, chunkMaxTokens: null } })),
    ).toBe(false);
  });

  it("top_k 같은 안전 노브 변경만으로는 경고하지 않는다", () => {
    expect(
      isReindexRequiringChange(config, makeSaveInput({ tuning: { ...TUNING, retrievalTopK: 20 } })),
    ).toBe(false);
  });
});

describe("toEmbeddingTestResult", () => {
  it("실측 차원을 담는다", () => {
    const result = toEmbeddingTestResult({
      ok: true,
      latency_ms: 88,
      model: "bge-m3",
      dimensions: REQUIRED_EMBEDDING_DIM,
    });

    expect(result).toEqual({
      ok: true,
      latencyMs: 88,
      model: "bge-m3",
      error: null,
      dimensions: REQUIRED_EMBEDDING_DIM,
    });
  });

  it("차원 누락은 0으로 접는다 — 검증 통과로 오독되지 않게", () => {
    expect(toEmbeddingTestResult({ ok: true, latency_ms: 1, model: "m" }).dimensions).toBe(0);
  });
});

describe("재색인·임베딩 테스트 호출", () => {
  it("testEmbeddingConfig 는 test-embedding 으로 임베딩 본문만 POST 한다", async () => {
    const fetchMock = stubFetch({
      ok: true,
      latency_ms: 91,
      model: "bge-m3",
      dimensions: 512,
    });

    const result = await testEmbeddingConfig({ baseUrl: "http://x/v1", model: "bge-m3" });

    expect(result.dimensions).toBe(512);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/system/ai-config/test-embedding");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      embedding_base_url: "http://x/v1",
      embedding_model: "bge-m3",
    });
  });

  it("startReindex 는 enqueue 건수를 매핑한다", async () => {
    const fetchMock = stubFetch({ enqueued_documents: 33, enqueued_notices: 7 });

    expect(await startReindex()).toEqual({ enqueuedDocuments: 33, enqueuedNotices: 7 });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/system/ai-config/reindex");
    expect(init.method).toBe("POST");
  });

  it("getReindexStatus 는 카운트를 매핑하고 누락은 0으로 접는다", async () => {
    stubFetch({ pending: 5, indexing: 1, indexed: 27, total: 33 });

    expect(await getReindexStatus()).toEqual({
      pending: 5,
      indexing: 1,
      indexed: 27,
      failed: 0,
      total: 33,
    });
  });

  it("isReindexRunning 은 대기·진행이 남아 있을 때만 true", () => {
    expect(isReindexRunning({ pending: 0, indexing: 0, indexed: 33, failed: 1, total: 34 })).toBe(
      false,
    );
    expect(isReindexRunning({ pending: 3, indexing: 0, indexed: 30, failed: 0, total: 33 })).toBe(
      true,
    );
    expect(isReindexRunning({ pending: 0, indexing: 2, indexed: 31, failed: 0, total: 33 })).toBe(
      true,
    );
  });

  it("실패 응답은 ApiError 로 던진다", async () => {
    stubFetch({ detail: "임베딩 차원이 1024가 아닙니다 (실측 512)." }, false, 422);

    await expect(startReindex()).rejects.toThrow("임베딩 차원이 1024가 아닙니다 (실측 512).");
  });
});
