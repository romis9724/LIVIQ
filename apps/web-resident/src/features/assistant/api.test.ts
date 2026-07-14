import { describe, expect, it } from "vitest";
import { parseSseBuffer } from "./api";

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
