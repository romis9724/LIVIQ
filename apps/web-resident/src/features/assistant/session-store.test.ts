import { describe, expect, it } from "vitest";
import { EMPTY_THREAD, parseThread, persistableMessages } from "./session-store";
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
    text: "매주 화요일에 배출합니다.",
    citations: [],
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
    // Arrange — 옛 스키마·손댄 값: 역할 불명, citations 없는 ai, 문자열
    const raw = JSON.stringify({
      messages: [user(), { id: "x", role: "ai", text: "no citations" }, { role: "bot" }, "oops"],
      conversationId: 42,
    });

    // Act
    const thread = parseThread(raw);

    // Assert
    expect(thread.messages).toEqual([user()]);
    expect(thread.conversationId).toBeNull();
  });
});
