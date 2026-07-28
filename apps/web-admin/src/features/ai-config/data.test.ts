import { describe, expect, it } from "vitest";

import {
  buildAiConfigPayload,
  toAiConfig,
  toAiTestResult,
  validateBaseUrl,
  validateModel,
  type AiConfigInput,
} from "./data";

function makeInput(over: Partial<AiConfigInput> = {}): AiConfigInput {
  return {
    baseUrl: "http://localhost:11434/v1",
    model: "llama3.1:8b",
    reasoningEffort: null,
    ...over,
  };
}

describe("toAiConfig (GET 응답 매핑)", () => {
  it("snake_case 응답을 camelCase 설정으로 옮긴다", () => {
    const config = toAiConfig({
      configured: true,
      source: "db",
      base_url: "https://llm.example.com/v1",
      model: "llama3.1:8b",
      reasoning_effort: "low",
      api_key_masked: "…abcd",
    });

    expect(config).toEqual({
      configured: true,
      source: "db",
      baseUrl: "https://llm.example.com/v1",
      model: "llama3.1:8b",
      reasoningEffort: "low",
      apiKeyMasked: "…abcd",
    });
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
