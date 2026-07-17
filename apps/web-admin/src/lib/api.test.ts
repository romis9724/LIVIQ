import { describe, it, expect } from "vitest";

import { buildInquiryQuery, buildListQuery } from "./api";

describe("buildListQuery", () => {
  it("파라미터 없으면 빈 문자열", () => {
    expect(buildListQuery({})).toBe("");
  });

  it("index_status 만 조립", () => {
    expect(buildListQuery({ indexStatus: "failed" })).toBe("?index_status=failed");
  });

  it("q 는 트림 후 인코딩해 붙인다", () => {
    expect(buildListQuery({ q: " 주차 " })).toBe("?q=%EC%A3%BC%EC%B0%A8");
  });

  it("공백뿐인 q 는 생략", () => {
    expect(buildListQuery({ q: "   " })).toBe("");
  });

  it("둘 다 있으면 함께 조립", () => {
    expect(buildListQuery({ indexStatus: "pending", q: "규약" })).toBe(
      "?index_status=pending&q=%EA%B7%9C%EC%95%BD",
    );
  });
});

describe("buildInquiryQuery", () => {
  it("파라미터 없으면 빈 문자열", () => {
    expect(buildInquiryQuery({})).toBe("");
  });

  it("status 만 조립", () => {
    expect(buildInquiryQuery({ status: "assigned" })).toBe("?status=assigned");
  });

  it("category_id 만 조립", () => {
    expect(buildInquiryQuery({ categoryId: "cat-1" })).toBe("?category_id=cat-1");
  });

  it("둘 다 있으면 함께 조립", () => {
    expect(buildInquiryQuery({ status: "done", categoryId: "cat-1" })).toBe(
      "?status=done&category_id=cat-1",
    );
  });
});
