import { describe, expect, it } from "vitest";

import { parseSseBuffer, toEvent } from "./assistant";

describe("parseSseBuffer (시설 도우미)", () => {
  it("CRLF(sse-starlette) 개행을 정규화해 완결 프레임을 파싱한다", () => {
    const buf = 'event: token\r\ndata: {"text":"덜컹"}\r\n\r\n';
    const [frames, rest] = parseSseBuffer(buf);
    expect(frames).toEqual([{ event: "token", data: '{"text":"덜컹"}' }]);
    expect(rest).toBe("");
  });

  it("미완결 프레임은 버퍼로 남긴다", () => {
    const buf = 'event: status\ndata: {"stage":"searching"}\n\nevent: to';
    const [frames, rest] = parseSseBuffer(buf);
    expect(frames).toHaveLength(1);
    expect(rest).toContain("event: to");
  });
});

describe("toEvent (SSE → 도메인)", () => {
  it("done의 tool_path(호출 도구 순서)를 매핑한다", () => {
    const event = toEvent({
      event: "done",
      data: JSON.stringify({
        conversation_id: "c1",
        status: "answered",
        confidence: 0.8,
        needs_review: false,
        tool_path: ["search_facility_graph", "get_facilities"],
      }),
    });
    expect(event).toEqual({
      type: "done",
      result: {
        messageId: null,
        conversationId: "c1",
        status: "answered",
        confidence: 0.8,
        needsReview: false,
        fallbackReason: null,
        toolPath: ["search_facility_graph", "get_facilities"],
      },
    });
  });

  it("tool_path 누락 시 빈 배열로 방어한다", () => {
    const event = toEvent({
      event: "done",
      data: JSON.stringify({ conversation_id: "c1", status: "fallback", confidence: 0, needs_review: false }),
    });
    expect(event?.type).toBe("done");
    if (event?.type === "done") expect(event.result.toolPath).toEqual([]);
  });

  it("도구 결과 인용은 document_id null로 매핑한다", () => {
    const event = toEvent({
      event: "citation",
      data: JSON.stringify({ ref: 1, document_id: null, document_title: "유사 장애·정비 이력", quote: "..." }),
    });
    expect(event).toEqual({
      type: "citation",
      citation: {
        ref: 1,
        documentId: null,
        documentTitle: "유사 장애·정비 이력",
        quote: "...",
        page: null,
        clause: null,
      },
    });
  });

  it("알 수 없는 이벤트·깨진 JSON은 null", () => {
    expect(toEvent({ event: "bogus", data: "{}" })).toBeNull();
    expect(toEvent({ event: "done", data: "{not-json" })).toBeNull();
  });
});
