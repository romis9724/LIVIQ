import { describe, expect, it } from "vitest";
import { parseLatestThread } from "./assistant-restore";

const raw = (messages: unknown[], conversationId: unknown = "conv-1") => ({
  conversation_id: conversationId,
  messages,
});

const serverMessage = (overrides: Record<string, unknown> = {}) => ({
  id: "11111111-1111-1111-1111-111111111111",
  role: "assistant",
  content: "매주 화요일에 배출합니다.",
  status: "answered",
  ...overrides,
});

describe("parseLatestThread", () => {
  it("restores user and assistant messages in order", () => {
    // Arrange
    const body = raw([
      { id: "u1", role: "user", content: "분리수거 언제예요?", status: null },
      serverMessage({ id: "a1" }),
    ]);

    // Act
    const thread = parseLatestThread(body);

    // Assert
    expect(thread.conversationId).toBe("conv-1");
    expect(thread.messages).toEqual([
      { id: "u1", role: "user", text: "분리수거 언제예요?" },
      {
        id: "a1",
        role: "ai",
        status: "done",
        stage: "verifying",
        tool: null,
        text: "매주 화요일에 배출합니다.",
        citations: [],
        steps: [],
        result: {
          messageId: "a1",
          conversationId: "conv-1",
          status: "answered",
          confidence: 0,
          needsReview: false,
          fallbackReason: null,
          answer: "매주 화요일에 배출합니다.",
          toolPath: [],
          suggestions: [],
        },
      },
    ]);
  });

  it("keeps clarify so the restored bubble is not shown as a failure", () => {
    const thread = parseLatestThread(raw([serverMessage({ status: "clarify" })]));

    expect(thread.messages[0]).toMatchObject({ result: { status: "clarify" } });
  });

  it("maps handed_off and unknown statuses to fallback", () => {
    for (const status of ["handed_off", "fallback", null, "무언가"]) {
      const thread = parseLatestThread(raw([serverMessage({ status })]));
      expect(thread.messages[0]).toMatchObject({ result: { status: "fallback" } });
    }
  });

  it("returns an empty thread when the shape is not a thread", () => {
    const empty = { conversationId: null, messages: [] };
    expect(parseLatestThread(null)).toEqual(empty);
    expect(parseLatestThread("nope")).toEqual(empty);
    expect(parseLatestThread({ conversation_id: null, messages: [] })).toEqual(empty);
    expect(parseLatestThread({ conversation_id: "conv-1", messages: "nope" })).toEqual(empty);
    // 대화 id 가 없으면 이어서 물을 수 없다 — 메시지만 되살리지 않는다.
    expect(parseLatestThread(raw([serverMessage()], null))).toEqual(empty);
  });

  it("drops entries that would break rendering", () => {
    // Arrange — 빈 본문, 알 수 없는 역할, id 없음, 메시지가 아닌 값
    const body = raw([
      serverMessage({ id: "a1", content: "" }),
      serverMessage({ id: "a2", role: "system" }),
      serverMessage({ id: 42 }),
      "oops",
      { id: "u1", role: "user", content: "남는 질문" },
    ]);

    // Act
    const thread = parseLatestThread(body);

    // Assert
    expect(thread.messages).toEqual([{ id: "u1", role: "user", text: "남는 질문" }]);
  });
});
