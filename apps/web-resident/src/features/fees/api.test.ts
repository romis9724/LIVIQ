import { describe, expect, it } from "vitest";
import { feeDelta, formatWon, toFeeEvent } from "./api";

describe("feeDelta — 전월 대비 차액(표시용)", () => {
  it("증가는 양수·up", () => {
    expect(feeDelta(238400, 210000)).toEqual({ amount: 28400, direction: "up" });
  });

  it("감소는 음수·down", () => {
    expect(feeDelta(200000, 210000)).toEqual({ amount: -10000, direction: "down" });
  });

  it("동일하면 flat", () => {
    expect(feeDelta(210000, 210000)).toEqual({ amount: 0, direction: "flat" });
  });

  it("total·prevTotal 어느 하나라도 null이면 null", () => {
    expect(feeDelta(null, 210000)).toBeNull();
    expect(feeDelta(238400, null)).toBeNull();
  });
});

describe("formatWon", () => {
  it("천단위 구분 + '원'", () => {
    expect(formatWon(238400)).toBe("238,400원");
    expect(formatWon(0)).toBe("0원");
  });
});

describe("toFeeEvent — SSE 프레임 매핑", () => {
  it("status → stage", () => {
    expect(toFeeEvent({ event: "status", data: '{"stage":"generating"}' })).toEqual({
      type: "status",
      stage: "generating",
    });
  });

  it("token → text", () => {
    expect(toFeeEvent({ event: "token", data: '{"text":"난방비"}' })).toEqual({
      type: "token",
      text: "난방비",
    });
  });

  it("citation → document_title·quote (document_id는 무시)", () => {
    const frame = {
      event: "citation",
      data: '{"ref":1,"document_id":null,"document_title":"관리비 확정 데이터","quote":"난방비 73,000원"}',
    };
    expect(toFeeEvent(frame)).toEqual({
      type: "citation",
      citation: { documentTitle: "관리비 확정 데이터", quote: "난방비 73,000원" },
    });
  });

  it("done → status·confidence·needsReview·fallbackReason", () => {
    const frame = {
      event: "done",
      data: '{"status":"answered","confidence":0.82,"needs_review":false,"fallback_reason":null}',
    };
    expect(toFeeEvent(frame)).toEqual({
      type: "done",
      result: { status: "answered", confidence: 0.82, needsReview: false, fallbackReason: null },
    });
  });

  it("미지원 이벤트·깨진 JSON은 null", () => {
    expect(toFeeEvent({ event: "ping", data: "{}" })).toBeNull();
    expect(toFeeEvent({ event: "token", data: "not-json" })).toBeNull();
  });
});
