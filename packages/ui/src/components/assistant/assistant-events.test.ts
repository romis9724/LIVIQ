import { describe, expect, it } from "vitest";
import {
  type AssistantDoneResult,
  answerKind,
  parseSseBuffer,
  streamAssistant,
  toEvent,
} from "./assistant-events";

describe("parseSseBuffer", () => {
  it("완결 프레임을 파싱하고 미완결 버퍼를 남긴다", () => {
    const buf =
      'event: status\ndata: {"stage":"searching"}\n\n' +
      'event: token\ndata: {"text":"안'; // 미완결 프레임
    const [frames, rest] = parseSseBuffer(buf);
    expect(frames).toHaveLength(1);
    expect(frames[0]).toEqual({ event: "status", data: '{"stage":"searching"}' });
    expect(rest).toContain("token");
  });

  it("여러 프레임을 순서대로 파싱한다", () => {
    const buf =
      'event: token\ndata: {"text":"가"}\n\n' +
      'event: token\ndata: {"text":"나"}\n\n' +
      'event: done\ndata: {"status":"answered"}\n\n';
    const [frames, rest] = parseSseBuffer(buf);
    expect(frames.map((f) => f.event)).toEqual(["token", "token", "done"]);
    expect(rest).toBe("");
  });

  it("CRLF 개행(sse-starlette)을 파싱한다", () => {
    const buf = 'event: token\r\ndata: {"text":"가"}\r\n\r\n';
    const [frames, rest] = parseSseBuffer(buf);
    expect(frames).toHaveLength(1);
    expect(frames[0]).toEqual({ event: "token", data: '{"text":"가"}' });
    expect(rest).toBe("");
  });

  it("data 없는 블록은 무시한다", () => {
    const [frames] = parseSseBuffer(": keep-alive\n\n");
    expect(frames).toHaveLength(0);
  });

  it("경계에서 잘린 청크를 이어붙여 파싱한다", () => {
    let buffer = 'event: cita';
    let [frames, rest] = parseSseBuffer(buffer);
    expect(frames).toHaveLength(0);
    buffer = rest + 'tion\ndata: {"ref":1}\n\n';
    [frames, rest] = parseSseBuffer(buffer);
    expect(frames).toHaveLength(1);
    expect(frames[0]?.event).toBe("citation");
  });
});

const doneFrame = (payload: Record<string, unknown>) => ({
  event: "done",
  data: JSON.stringify({
    conversation_id: "c1",
    status: "answered",
    confidence: 0.9,
    needs_review: false,
    ...payload,
  }),
});

describe("toEvent — done 이벤트", () => {
  it("tool_path 를 toolPath 로 옮긴다", () => {
    const event = toEvent(doneFrame({ tool_path: ["search_similar_inquiries"] }));
    expect(event?.type).toBe("done");
    expect(event?.type === "done" && event.result.toolPath).toEqual([
      "search_similar_inquiries",
    ]);
  });

  it("tool_path 가 없으면 빈 배열이다", () => {
    const event = toEvent(doneFrame({}));
    expect(event?.type === "done" && event.result.toolPath).toEqual([]);
  });

  it("clarify 상태를 그대로 옮긴다", () => {
    const event = toEvent(doneFrame({ status: "clarify", answer: "몇 월 관리비인가요?" }));
    expect(event?.type === "done" && event.result.status).toBe("clarify");
    expect(event?.type === "done" && event.result.answer).toBe("몇 월 관리비인가요?");
  });
});

describe("toEvent — H18 additive 필드", () => {
  it("status.tool 을 옮긴다(없으면 null — 구버전 서버 하위호환)", () => {
    const withTool = toEvent({ event: "status", data: '{"stage":"searching","tool":"get_fees"}' });
    expect(withTool).toEqual({ type: "status", stage: "searching", tool: "get_fees" });
    const withoutTool = toEvent({ event: "status", data: '{"stage":"generating"}' });
    expect(withoutTool).toEqual({ type: "status", stage: "generating", tool: null });
  });

  it("citation.data 를 그대로 옮긴다(문서 인용은 null)", () => {
    const tool = toEvent({
      event: "citation",
      data: '{"ref":1,"document_title":"관리비","quote":"q","data":{"kind":"fee_table"}}',
    });
    expect(tool?.type === "citation" && tool.citation.data).toEqual({ kind: "fee_table" });
    const doc = toEvent({
      event: "citation",
      data: '{"ref":2,"document_id":"d1","document_title":"관리규약","quote":"q"}',
    });
    expect(doc?.type === "citation" && doc.citation.data).toBeNull();
  });

  it("done.suggestions 를 옮긴다(없으면 빈 배열)", () => {
    const event = toEvent(doneFrame({ suggestions: ["지난달과 비교하기"] }));
    expect(event?.type === "done" && event.result.suggestions).toEqual(["지난달과 비교하기"]);
    expect(toEvent(doneFrame({}))).toMatchObject({ result: { suggestions: [] } });
  });
});

describe("streamAssistant — 앱 주입(URL·인증 fetch)", () => {
  const sse = (text: string) =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(text));
        controller.close();
      },
    });

  it("앱의 apiFetch 로 POST 하고 프레임을 이벤트로 흘린다", async () => {
    // Arrange — ui 는 엔드포인트도 인증도 모른다: 둘 다 호출부가 준다.
    const calls: Array<[string, RequestInit | undefined]> = [];
    const apiFetch = async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return new Response(sse('event: token\ndata: {"text":"가"}\n\nevent: done\ndata: {"conversation_id":"c1","status":"answered","confidence":0.9,"needs_review":false}\n\n'));
    };

    // Act
    const events = [];
    for await (const e of streamAssistant("/x/ask", { question: "질문" }, { apiFetch })) {
      events.push(e);
    }

    // Assert
    expect(calls[0]?.[0]).toBe("/x/ask");
    expect(calls[0]?.[1]?.method).toBe("POST");
    expect(calls[0]?.[1]?.body).toBe(JSON.stringify({ question: "질문" }));
    expect(events.map((e) => e.type)).toEqual(["token", "done"]);
  });

  it("실패 응답은 던진다(호출부가 폴백 말풍선으로 받는다)", async () => {
    // Arrange
    const apiFetch = async () => new Response("nope", { status: 500 });

    // Act · Assert
    await expect(
      streamAssistant("/x/ask", {}, { apiFetch }).next(),
    ).rejects.toThrow("assistant 요청 실패: 500");
  });
});

describe("answerKind — 되묻기 분기", () => {
  const result = (status: AssistantDoneResult["status"]) => ({ status });

  it("되묻기는 폴백이 아니라 clarify 로 분기한다", () => {
    expect(answerKind({ status: "done", result: result("clarify") })).toBe("clarify");
  });

  it("스트리밍 중에는 상태와 무관하게 streaming 이다", () => {
    expect(answerKind({ status: "streaming", result: result("clarify") })).toBe("streaming");
  });

  it("네트워크 오류는 되묻기보다 우선해 폴백이다", () => {
    expect(answerKind({ status: "done", error: true, result: result("clarify") })).toBe(
      "fallback",
    );
  });

  it("기존 두 상태는 그대로 분기한다(회귀)", () => {
    expect(answerKind({ status: "done", result: result("answered") })).toBe("answered");
    expect(answerKind({ status: "done", result: result("fallback") })).toBe("fallback");
    expect(answerKind({ status: "done" })).toBe("fallback"); // done 이벤트 없이 끝난 경우
  });
});
