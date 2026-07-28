// @vitest-environment jsdom
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AiConfig } from "./data";

const getAiConfig = vi.fn();
const saveAiConfig = vi.fn();
const testAiConfig = vi.fn();
const testEmbeddingConfig = vi.fn();
const startReindex = vi.fn();
const getReindexStatus = vi.fn();

vi.mock("./data", async (importOriginal) => {
  // 순수 매핑·검증은 실제 구현을 그대로 쓰고 네트워크 호출만 대체한다.
  const actual = await importOriginal<typeof import("./data")>();
  return {
    ...actual,
    getAiConfig: () => getAiConfig(),
    saveAiConfig: (input: unknown) => saveAiConfig(input),
    testAiConfig: (input: unknown) => testAiConfig(input),
    testEmbeddingConfig: (input: unknown) => testEmbeddingConfig(input),
    startReindex: () => startReindex(),
    getReindexStatus: () => getReindexStatus(),
  };
});

import { AiConfigPanel } from "./AiConfigPanel";

const TUNING: AiConfig["tuning"] = {
  chunkMaxTokens: 400,
  retrievalTopK: 8,
  llmMaxOutputTokens: 1024,
  llmTimeoutS: 60,
  toolConfidence: 0.8,
  answerCacheTtlS: 3600,
};

const ENV_CONFIG: AiConfig = {
  configured: false,
  source: "env",
  baseUrl: "http://localhost:11434/v1",
  model: "llama3.1:8b",
  reasoningEffort: null,
  apiKeyMasked: null,
  embeddingBaseUrl: "http://localhost:11434/v1",
  embeddingModel: "bge-m3",
  embeddingApiKeyMasked: null,
  embeddingSource: "env",
  tuning: TUNING,
};

const DB_CONFIG: AiConfig = {
  configured: true,
  source: "db",
  baseUrl: "https://llm.example.com/v1",
  model: "qwen2.5:14b",
  reasoningEffort: "low",
  apiKeyMasked: "…abcd",
  embeddingBaseUrl: "https://embed.example.com/v1",
  embeddingModel: "bge-m3",
  embeddingApiKeyMasked: "…wxyz",
  embeddingSource: "db",
  tuning: TUNING,
};

beforeEach(() => {
  getAiConfig.mockResolvedValue(ENV_CONFIG);
  getReindexStatus.mockResolvedValue({ pending: 0, indexing: 0, indexed: 33, failed: 0, total: 33 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("AiConfigPanel", () => {
  it("현재 설정을 폼 기본값으로 채운다", async () => {
    getAiConfig.mockResolvedValue(DB_CONFIG);
    render(<AiConfigPanel />);

    const baseUrl = (await screen.findByLabelText(/^base URL/)) as HTMLInputElement;
    expect(baseUrl.value).toBe("https://llm.example.com/v1");
    expect((screen.getByLabelText(/^모델명/) as HTMLInputElement).value).toBe("qwen2.5:14b");
    expect((screen.getByLabelText("reasoning effort") as HTMLSelectElement).value).toBe("low");
  });

  it("source=env면 env 기본값 안내를 보여준다", async () => {
    render(<AiConfigPanel />);
    expect(await screen.findByText(/^env 기본값 사용 중/)).toBeDefined();
    expect(screen.getByText(/^임베딩은 env 기본값 사용 중/)).toBeDefined();
  });

  it("저장된 키는 마스킹 값만 placeholder·도움말로 노출한다", async () => {
    getAiConfig.mockResolvedValue(DB_CONFIG);
    render(<AiConfigPanel />);

    const key = (await screen.findByLabelText("API 키")) as HTMLInputElement;
    expect(key.type).toBe("password");
    expect(key.value).toBe("");
    expect(key.placeholder).toBe("…abcd");
    expect(screen.getByText(/현재 키 …abcd/)).toBeDefined();
  });

  it("필수 값이 비면 저장을 호출하지 않고 에러를 보여준다", async () => {
    render(<AiConfigPanel />);
    const baseUrl = (await screen.findByLabelText(/^base URL/)) as HTMLInputElement;
    baseUrl.value = "";

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(screen.getByText("base URL을 입력하세요.")).toBeDefined());
    expect(saveAiConfig).not.toHaveBeenCalled();
  });

  it("연결 테스트 성공 결과를 인라인으로 보여준다", async () => {
    testAiConfig.mockResolvedValue({
      ok: true,
      latencyMs: 412,
      model: "llama3.1:8b",
      error: null,
    });
    render(<AiConfigPanel />);
    await screen.findByLabelText(/^base URL/);

    fireEvent.click(screen.getByRole("button", { name: "연결 테스트" }));

    expect(await screen.findByText("응답 OK · 412ms · llama3.1:8b")).toBeDefined();
    // 빈 키는 "기존 유지" — api_key 를 담지 않는다.
    expect(testAiConfig).toHaveBeenCalledWith({
      baseUrl: "http://localhost:11434/v1",
      model: "llama3.1:8b",
      apiKey: undefined,
      reasoningEffort: null,
    });
  });

  it("연결 테스트 실패 사유를 인라인으로 보여준다", async () => {
    testAiConfig.mockResolvedValue({
      ok: false,
      latencyMs: 12,
      model: "llama3.1:8b",
      error: "connection refused",
    });
    render(<AiConfigPanel />);
    await screen.findByLabelText(/^base URL/);

    fireEvent.click(screen.getByRole("button", { name: "연결 테스트" }));

    expect(await screen.findByText(/connection refused/)).toBeDefined();
  });

  it("설정 조회 실패는 안내 화면으로 대체한다", async () => {
    getAiConfig.mockRejectedValue(new Error("권한이 없습니다."));
    render(<AiConfigPanel />);

    expect(await screen.findByText("설정을 불러오지 못했습니다")).toBeDefined();
    expect(screen.getByText("권한이 없습니다.")).toBeDefined();
  });
});

describe("AiConfigPanel — 임베딩 섹션 (H15-3)", () => {
  it("임베딩·노브 값을 폼 기본값으로 채운다", async () => {
    getAiConfig.mockResolvedValue(DB_CONFIG);
    render(<AiConfigPanel />);

    const embedUrl = (await screen.findByLabelText(/^임베딩 base URL/)) as HTMLInputElement;
    expect(embedUrl.value).toBe("https://embed.example.com/v1");
    expect((screen.getByLabelText(/^임베딩 모델명/) as HTMLInputElement).value).toBe("bge-m3");
    expect((screen.getByLabelText("검색 top_k") as HTMLInputElement).value).toBe("8");
    expect((screen.getByLabelText("도구 confidence") as HTMLInputElement).value).toBe("0.8");
  });

  it("재색인 경고문을 상시 노출한다", async () => {
    render(<AiConfigPanel />);
    expect(await screen.findByText(/임베딩 설정을 바꾸면 문서 전량 재색인이 필요합니다/)).toBeDefined();
  });

  it("차원이 1024가 아니면 실패로 표시하고 필요한 차원을 안내한다", async () => {
    testEmbeddingConfig.mockResolvedValue({
      ok: true,
      latencyMs: 55,
      model: "e5-large",
      dimensions: 512,
      error: null,
    });
    render(<AiConfigPanel />);
    await screen.findByLabelText(/^base URL/);

    fireEvent.click(screen.getByRole("button", { name: "임베딩 연결 테스트" }));

    const result = await screen.findByText(/512차원/);
    expect(result.textContent).toContain("1024차원 필요");
    expect(result.className).toContain("ai-cfg__result--fail");
    expect(testEmbeddingConfig).toHaveBeenCalledWith({
      baseUrl: "http://localhost:11434/v1",
      model: "bge-m3",
      apiKey: undefined,
    });
  });

  it("차원이 1024면 성공으로 표시한다", async () => {
    testEmbeddingConfig.mockResolvedValue({
      ok: true,
      latencyMs: 55,
      model: "bge-m3",
      dimensions: 1024,
      error: null,
    });
    render(<AiConfigPanel />);
    await screen.findByLabelText(/^base URL/);

    fireEvent.click(screen.getByRole("button", { name: "임베딩 연결 테스트" }));

    const result = await screen.findByText(/응답 OK · 55ms · bge-m3 · 1024차원/);
    expect(result.className).toContain("ai-cfg__result--ok");
  });
});

describe("AiConfigPanel — 저장 경고·노브 검증 (H15-3)", () => {
  it("위험 변경(임베딩 모델)은 확인을 받고서야 저장한다", async () => {
    saveAiConfig.mockResolvedValue(ENV_CONFIG);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<AiConfigPanel />);
    const embedModel = (await screen.findByLabelText(/^임베딩 모델명/)) as HTMLInputElement;
    fireEvent.change(embedModel, { target: { value: "e5-large" } });

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(saveAiConfig).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(saveAiConfig).toHaveBeenCalledTimes(1));
    expect(saveAiConfig).toHaveBeenCalledWith(
      expect.objectContaining({ embedding: expect.objectContaining({ model: "e5-large" }) }),
    );
  });

  it("안전 노브만 바꾸면 확인 없이 저장한다", async () => {
    saveAiConfig.mockResolvedValue(ENV_CONFIG);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<AiConfigPanel />);
    const topK = (await screen.findByLabelText("검색 top_k")) as HTMLInputElement;
    fireEvent.change(topK, { target: { value: "20" } });

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(saveAiConfig).toHaveBeenCalledTimes(1));
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(saveAiConfig).toHaveBeenCalledWith(
      expect.objectContaining({ tuning: expect.objectContaining({ retrievalTopK: 20 }) }),
    );
  });

  it("빈 노브는 기본값 복귀(null)로 전송한다", async () => {
    saveAiConfig.mockResolvedValue(ENV_CONFIG);
    render(<AiConfigPanel />);
    const topK = (await screen.findByLabelText("검색 top_k")) as HTMLInputElement;
    fireEvent.change(topK, { target: { value: "" } });

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(saveAiConfig).toHaveBeenCalledTimes(1));
    expect(saveAiConfig).toHaveBeenCalledWith(
      expect.objectContaining({ tuning: expect.objectContaining({ retrievalTopK: null }) }),
    );
  });

  it("노브가 범위를 벗어나면 저장하지 않고 에러를 보여준다", async () => {
    render(<AiConfigPanel />);
    const topK = (await screen.findByLabelText("검색 top_k")) as HTMLInputElement;
    fireEvent.change(topK, { target: { value: "99" } });

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(screen.getByText("1~50 범위로 입력하세요.")).toBeDefined());
    expect(saveAiConfig).not.toHaveBeenCalled();
  });
});

describe("AiConfigPanel — 재색인 섹션 (H15-3)", () => {
  it("색인 현황을 카운트로 보여준다", async () => {
    getReindexStatus.mockResolvedValue({
      pending: 5,
      indexing: 1,
      indexed: 27,
      failed: 1,
      total: 34,
    });
    render(<AiConfigPanel />);

    expect(await screen.findByText("대기 5 · 진행 1 · 완료 27 · 실패 1 / 34")).toBeDefined();
  });

  it("재색인은 확인을 받고서야 호출하고 enqueue 건수를 알린다", async () => {
    startReindex.mockResolvedValue({ enqueuedDocuments: 33, enqueuedNotices: 7 });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<AiConfigPanel />);
    const button = await screen.findByRole("button", { name: "재색인 시작" });

    fireEvent.click(button);

    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(startReindex).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    fireEvent.click(button);

    expect(await screen.findByText(/문서 33건 · 공지 7건/)).toBeDefined();
  });
});
