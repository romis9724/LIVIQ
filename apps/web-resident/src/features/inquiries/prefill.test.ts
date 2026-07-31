import { describe, expect, it } from "vitest";
import {
  INQUIRY_BODY_MAX,
  INQUIRY_TITLE_MAX,
  buildComposeHref,
  readComposePrefill,
} from "./prefill";

describe("buildComposeHref", () => {
  it("질문 원문을 제목·본문에 실은 접수 딥링크를 만든다", () => {
    const href = buildComposeHref("엘리베이터가 고장났어요");
    const params = new URLSearchParams(href.split("?")[1]);
    expect(href.startsWith("/inquiries?")).toBe(true);
    expect(params.get("compose")).toBe("1");
    expect(params.get("title")).toBe("엘리베이터가 고장났어요");
    expect(params.get("body")).toBe("엘리베이터가 고장났어요");
  });

  it("40자 넘는 질문은 제목만 줄이고 본문은 전문을 유지한다", () => {
    const question = "가".repeat(50);
    const params = new URLSearchParams(buildComposeHref(question).split("?")[1]);
    expect(params.get("title")).toBe(`${"가".repeat(40)}…`);
    expect(params.get("body")).toBe(question);
  });

  it("특수문자를 인코딩해 쿼리 구조를 깨뜨리지 않는다", () => {
    const href = buildComposeHref("주차 & 소음 = 민원? #1동");
    expect(href).not.toContain("#");
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("body")).toBe("주차 & 소음 = 민원? #1동");
  });
});

describe("readComposePrefill", () => {
  const read = (query: string) => readComposePrefill(new URLSearchParams(query));

  it("compose=1 이면 제목·본문을 초기값으로 넘긴다", () => {
    expect(read("compose=1&title=%EC%86%8C%EC%9D%8C&body=%EB%B0%A4%EC%97%90")).toEqual({
      isCompose: true,
      title: "소음",
      body: "밤에",
    });
  });

  it("compose 가 없으면 title·body 가 있어도 전부 버린다", () => {
    expect(read("title=소음&body=밤에")).toEqual({
      isCompose: false,
      title: "",
      body: "",
    });
  });

  it("빠진 파라미터는 빈 문자열이다", () => {
    expect(read("compose=1")).toEqual({ isCompose: true, title: "", body: "" });
  });

  it("폼 상한을 넘는 값은 잘라낸다(URL 은 신뢰할 수 없는 입력)", () => {
    const params = new URLSearchParams({
      compose: "1",
      title: "가".repeat(INQUIRY_TITLE_MAX + 10),
      body: "나".repeat(INQUIRY_BODY_MAX + 10),
    });
    const prefill = readComposePrefill(params);
    expect(prefill.title).toHaveLength(INQUIRY_TITLE_MAX);
    expect(prefill.body).toHaveLength(INQUIRY_BODY_MAX);
  });

  it("왕복 — 만든 링크를 그대로 다시 읽으면 질문이 복원된다", () => {
    const question = "1203동 엘리베이터에서 쿵 소리가 나요";
    const href = buildComposeHref(question);
    const prefill = readComposePrefill(new URLSearchParams(href.split("?")[1]));
    expect(prefill).toEqual({ isCompose: true, title: question, body: question });
  });
});
