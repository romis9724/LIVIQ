import { afterEach, describe, expect, it, vi } from "vitest";
import {
  EMPTY_THREAD,
  THREAD_STORAGE_KEY,
  clearThread,
  parseThread,
  persistableMessages,
  readThread,
} from "./session-store";
import type { AiMessage, ChatMessage, UserMessage } from "./useAssistantStream";

function user(overrides: Partial<UserMessage> = {}): UserMessage {
  return { id: "m1", role: "user", text: "분리수거 배출 시간", ...overrides };
}

function ai(overrides: Partial<AiMessage> = {}): AiMessage {
  return {
    id: "m2",
    role: "ai",
    status: "done",
    stage: "verifying",
    tool: null,
    text: "매주 화요일에 배출합니다.",
    citations: [],
    steps: ["단지 문서 검색", "답변 작성"],
    ...overrides,
  };
}

describe("persistableMessages", () => {
  it("keeps completed messages", () => {
    // Arrange
    const messages: ChatMessage[] = [user(), ai()];

    // Act
    const kept = persistableMessages(messages);

    // Assert
    expect(kept).toEqual(messages);
  });

  it("drops a streaming ai message so no ghost bubble is restored", () => {
    // Arrange — 스트리밍 중 스냅샷(반쪽 텍스트 + 깜빡이는 커서)
    const streaming = ai({ id: "m4", status: "streaming", text: "매주 화" });

    // Act
    const kept = persistableMessages([user(), ai(), user({ id: "m3" }), streaming]);

    // Assert
    expect(kept.map((m) => m.id)).toEqual(["m1", "m2", "m3"]);
  });

  it("caps the stored history to the most recent messages", () => {
    // Arrange
    const messages = Array.from({ length: 50 }, (_, i) => user({ id: `m${i}` }));

    // Act
    const kept = persistableMessages(messages);

    // Assert
    expect(kept).toHaveLength(40);
    expect(kept[0]?.id).toBe("m10");
  });
});

describe("parseThread", () => {
  it("restores messages and the conversation id", () => {
    // Arrange
    const raw = JSON.stringify({ messages: [user(), ai()], conversationId: "conv-1" });

    // Act
    const thread = parseThread(raw);

    // Assert
    expect(thread.conversationId).toBe("conv-1");
    expect(thread.messages).toHaveLength(2);
  });

  it("falls back to an empty thread when nothing is stored", () => {
    expect(parseThread(null)).toEqual(EMPTY_THREAD);
  });

  it("falls back to an empty thread when the stored json is broken", () => {
    expect(parseThread("{not json")).toEqual(EMPTY_THREAD);
  });

  it("falls back to an empty thread when the shape is not a thread", () => {
    expect(parseThread(JSON.stringify({ messages: "nope" }))).toEqual(EMPTY_THREAD);
    expect(parseThread(JSON.stringify([1, 2, 3]))).toEqual(EMPTY_THREAD);
  });

  it("drops entries that would break rendering", () => {
    // Arrange — 옛 스키마·손댄 값: 역할 불명, citations/steps 없는 ai, 문자열
    const raw = JSON.stringify({
      messages: [
        user(),
        { id: "x", role: "ai", text: "no citations" },
        { id: "y", role: "ai", text: "no steps", citations: [] },
        { role: "bot" },
        "oops",
      ],
      conversationId: 42,
    });

    // Act
    const thread = parseThread(raw);

    // Assert
    expect(thread.messages).toEqual([user()]);
    expect(thread.conversationId).toBeNull();
  });
});

describe("clearThread", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("stores an empty-thread marker instead of deleting the key", () => {
    // Arrange — node 환경이라 sessionStorage 를 직접 세운다. 키를 지우면 다음 리로드의
    // 서버 복원이 방금 끊은 대화를 되살린다 — 마커가 남아야 한다(ADR-0027 결정 1).
    const store = new Map([[THREAD_STORAGE_KEY, JSON.stringify({ messages: [user()] })]]);
    vi.stubGlobal("window", {
      sessionStorage: {
        setItem: (key: string, value: string) => store.set(key, value),
      },
    });

    // Act
    clearThread();

    // Assert — 키는 남고 내용은 빈 스레드
    const marker = parseThread(store.get(THREAD_STORAGE_KEY) ?? null);
    expect(marker.messages).toEqual([]);
    expect(marker.conversationId).toBeNull();
  });

  it("stays silent when storage is unavailable", () => {
    // Arrange — 프라이빗 모드 등 접근이 던지는 환경
    vi.stubGlobal("window", {
      get sessionStorage(): never {
        throw new Error("denied");
      },
    });

    // Act · Assert — 새 대화 자체는 계속돼야 한다
    expect(() => clearThread()).not.toThrow();
  });
});

describe("readThread", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns null when nothing was ever stored (server-restore fallback)", () => {
    // Arrange
    vi.stubGlobal("window", {
      sessionStorage: { getItem: () => null },
    });

    // Act · Assert — "저장된 적 없음"은 빈 스레드와 다르다
    expect(readThread()).toBeNull();
  });

  it("returns the empty-thread marker as a thread, not null", () => {
    // Arrange — "새 대화" 마커: 서버 복원을 건너뛰게 하는 근거
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: () => JSON.stringify({ messages: [], conversationId: null }),
      },
    });

    // Act
    const thread = readThread();

    // Assert
    expect(thread).not.toBeNull();
    expect(thread?.messages).toEqual([]);
  });

  it("returns null when storage access throws (SSR·private mode)", () => {
    // Arrange
    vi.stubGlobal("window", {
      get sessionStorage(): never {
        throw new Error("denied");
      },
    });

    // Act · Assert
    expect(readThread()).toBeNull();
  });
});
