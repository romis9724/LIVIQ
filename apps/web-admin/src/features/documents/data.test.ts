import { describe, it, expect } from "vitest";

import type { DocumentItem } from "@/lib/api";
import { filterDocs, hasActiveIndexing, shortDate, summarize } from "./data";

function doc(overrides: Partial<DocumentItem>): DocumentItem {
  return {
    id: overrides.id ?? "id",
    title: overrides.title ?? "제목",
    sourceType: overrides.sourceType ?? "규약",
    visibility: overrides.visibility ?? "ALL",
    indexStatus: overrides.indexStatus ?? "indexed",
    createdAt: overrides.createdAt ?? "2026-06-01T00:00:00Z",
  };
}

describe("summarize", () => {
  it("상태별 개수를 집계한다", () => {
    const docs = [
      doc({ id: "1", indexStatus: "indexed" }),
      doc({ id: "2", indexStatus: "indexed" }),
      doc({ id: "3", indexStatus: "indexing" }),
      doc({ id: "4", indexStatus: "pending" }),
      doc({ id: "5", indexStatus: "failed" }),
    ];
    expect(summarize(docs)).toEqual({ indexed: 2, indexing: 1, pending: 1, failed: 1 });
  });

  it("빈 목록은 모두 0", () => {
    expect(summarize([])).toEqual({ indexed: 0, indexing: 0, pending: 0, failed: 0 });
  });
});

describe("filterDocs", () => {
  const docs = [
    doc({ id: "1", title: "주차장 운영 세칙", indexStatus: "indexed" }),
    doc({ id: "2", title: "분리수거 안내문", indexStatus: "failed" }),
    doc({ id: "3", title: "관리규약", indexStatus: "indexed" }),
  ];

  it("상태 all 은 전부 통과", () => {
    expect(filterDocs(docs, "all", "").length).toBe(3);
  });

  it("상태 필터는 해당 상태만 남긴다", () => {
    const result = filterDocs(docs, "failed", "");
    expect(result.map((d) => d.id)).toEqual(["2"]);
  });

  it("제목 부분일치(대소문자 무시)로 좁힌다", () => {
    expect(filterDocs(docs, "all", "주차").map((d) => d.id)).toEqual(["1"]);
  });

  it("상태와 검색을 동시에 적용한다", () => {
    expect(filterDocs(docs, "indexed", "관리").map((d) => d.id)).toEqual(["3"]);
  });
});

describe("hasActiveIndexing", () => {
  it("pending·indexing 이 있으면 true", () => {
    expect(hasActiveIndexing([doc({ indexStatus: "pending" })])).toBe(true);
    expect(hasActiveIndexing([doc({ indexStatus: "indexing" })])).toBe(true);
  });

  it("전부 indexed/failed 면 false", () => {
    expect(
      hasActiveIndexing([doc({ indexStatus: "indexed" }), doc({ indexStatus: "failed" })]),
    ).toBe(false);
  });
});

describe("shortDate", () => {
  it("ISO → MM/DD", () => {
    expect(shortDate("2026-06-01T09:30:00Z")).toMatch(/^0[56]\/\d{2}$/);
  });

  it("잘못된 값은 대시", () => {
    expect(shortDate("nonsense")).toBe("—");
  });
});
