import { describe, it, expect } from "vitest";

import type { DocumentItem } from "@/lib/api";
import {
  filterDocs,
  formatFileSize,
  hasActiveIndexing,
  shortDate,
  summarize,
  validateAttachment,
} from "./data";

function doc(overrides: Partial<DocumentItem>): DocumentItem {
  return {
    id: overrides.id ?? "id",
    title: overrides.title ?? "제목",
    sourceType: overrides.sourceType ?? "규약",
    visibility: overrides.visibility ?? "ALL",
    body: overrides.body ?? null,
    version: overrides.version ?? 1,
    indexStatus: overrides.indexStatus ?? "indexed",
    createdAt: overrides.createdAt ?? "2026-06-01T00:00:00Z",
    updatedAt: overrides.updatedAt ?? "2026-06-01T00:00:00Z",
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
  it("ISO → YYYY.MM.DD", () => {
    expect(shortDate("2026-06-01T09:30:00Z")).toMatch(/^2026\.0[56]\.\d{2}$/);
  });

  it("잘못된 값·null 은 대시", () => {
    expect(shortDate("nonsense")).toBe("—");
    expect(shortDate(null)).toBe("—");
  });
});

describe("validateAttachment", () => {
  it("허용 확장자·정상 크기는 통과(null)", () => {
    expect(validateAttachment({ name: "규약.pdf", size: 1024 })).toBeNull();
    expect(validateAttachment({ name: "MEMO.MD", size: 10 })).toBeNull();
    expect(validateAttachment({ name: "a.markdown", size: 10 })).toBeNull();
  });

  it("미허용 확장자는 거절", () => {
    expect(validateAttachment({ name: "회의록.hwp", size: 1024 })).toContain("허용 형식");
    expect(validateAttachment({ name: "이미지.png", size: 1024 })).toContain("허용 형식");
  });

  it("빈 파일은 거절", () => {
    expect(validateAttachment({ name: "a.txt", size: 0 })).toContain("빈 파일");
  });

  it("20MB 초과는 거절", () => {
    expect(validateAttachment({ name: "a.pdf", size: 20 * 1024 * 1024 + 1 })).toContain("20MB");
  });
});

describe("formatFileSize", () => {
  it("단위별 표기", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(1.5 * 1024 * 1024)).toBe("1.5 MB");
    expect(formatFileSize(15 * 1024 * 1024)).toBe("15 MB");
  });
});
