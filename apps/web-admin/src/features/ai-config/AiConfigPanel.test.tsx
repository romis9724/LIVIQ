// @vitest-environment jsdom
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AiConfig } from "./data";

const getAiConfig = vi.fn();
const saveAiConfig = vi.fn();
const testAiConfig = vi.fn();

vi.mock("./data", async (importOriginal) => {
  // 순수 매핑·검증은 실제 구현을 그대로 쓰고 네트워크 3종만 대체한다.
  const actual = await importOriginal<typeof import("./data")>();
  return {
    ...actual,
    getAiConfig: () => getAiConfig(),
    saveAiConfig: (input: unknown) => saveAiConfig(input),
    testAiConfig: (input: unknown) => testAiConfig(input),
  };
});

import { AiConfigPanel } from "./AiConfigPanel";

const ENV_CONFIG: AiConfig = {
  configured: false,
  source: "env",
  baseUrl: "http://localhost:11434/v1",
  model: "llama3.1:8b",
  reasoningEffort: null,
  apiKeyMasked: null,
};

const DB_CONFIG: AiConfig = {
  configured: true,
  source: "db",
  baseUrl: "https://llm.example.com/v1",
  model: "qwen2.5:14b",
  reasoningEffort: "low",
  apiKeyMasked: "…abcd",
};

beforeEach(() => {
  getAiConfig.mockResolvedValue(ENV_CONFIG);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AiConfigPanel", () => {
  it("현재 설정을 폼 기본값으로 채운다", async () => {
    getAiConfig.mockResolvedValue(DB_CONFIG);
    render(<AiConfigPanel />);

    const baseUrl = (await screen.findByLabelText(/base URL/)) as HTMLInputElement;
    expect(baseUrl.value).toBe("https://llm.example.com/v1");
    expect((screen.getByLabelText(/모델명/) as HTMLInputElement).value).toBe("qwen2.5:14b");
    expect((screen.getByLabelText("reasoning effort") as HTMLSelectElement).value).toBe("low");
  });

  it("source=env면 env 기본값 안내를 보여준다", async () => {
    render(<AiConfigPanel />);
    expect(await screen.findByText(/env 기본값 사용 중/)).toBeDefined();
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
    const baseUrl = (await screen.findByLabelText(/base URL/)) as HTMLInputElement;
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
    await screen.findByLabelText(/base URL/);

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
    await screen.findByLabelText(/base URL/);

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
