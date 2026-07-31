import { describe, expect, test } from "vitest";
import type { Citation } from "./api";
import { citationDetail, groupCitations } from "./sources";

function cite(over: Partial<Citation>): Citation {
  return {
    ref: 1,
    documentId: "doc-1",
    documentTitle: "첫마을4단지 관리규약",
    quote: "…",
    page: null,
    clause: null,
    data: null,
    ...over,
  } as Citation;
}

describe("citationDetail", () => {
  test("조항과 페이지를 함께 표기한다", () => {
    expect(citationDetail(cite({ clause: "제5조", page: 12 }))).toBe("제5조 · 12p");
  });

  test("둘 다 없으면 빈 문자열", () => {
    expect(citationDetail(cite({}))).toBe("");
  });
});

describe("groupCitations", () => {
  test("같은 문서의 여러 청크를 한 카드로 묶는다", () => {
    const grouped = groupCitations([
      cite({ ref: 1, clause: "제5조" }),
      cite({ ref: 2, clause: "제60조" }),
      cite({ ref: 3, clause: "제5조" }), // 같은 조항이 두 청크 → 표기 1회
    ]);

    expect(grouped).toHaveLength(1);
    expect(grouped[0]).toMatchObject({
      ref: 1,
      title: "첫마을4단지 관리규약",
      details: ["제5조", "제60조"],
      count: 3,
    });
  });

  test("문서가 다르면 따로 남는다", () => {
    const grouped = groupCitations([
      cite({ ref: 1, documentId: "doc-1", documentTitle: "관리규약" }),
      cite({ ref: 2, documentId: "doc-2", documentTitle: "회의록" }),
    ]);

    expect(grouped.map((g) => g.title)).toEqual(["관리규약", "회의록"]);
  });

  test("도구 카드(documentId 없음)는 제목으로 묶는다", () => {
    const grouped = groupCitations([
      cite({ ref: 1, documentId: null, documentTitle: "가까운 빈 주차자리" }),
      cite({ ref: 2, documentId: null, documentTitle: "가까운 빈 주차자리" }),
      cite({ ref: 3, documentId: null, documentTitle: "유사 민원 처리 사례" }),
    ]);

    expect(grouped.map((g) => [g.title, g.count])).toEqual([
      ["가까운 빈 주차자리", 2],
      ["유사 민원 처리 사례", 1],
    ]);
  });

  test("입력 순서를 유지한다 — 상위 근거가 앞", () => {
    const grouped = groupCitations([
      cite({ ref: 5, documentId: "doc-b", documentTitle: "B" }),
      cite({ ref: 1, documentId: "doc-a", documentTitle: "A" }),
    ]);

    expect(grouped.map((g) => g.title)).toEqual(["B", "A"]);
  });

  test("빈 입력은 빈 배열", () => {
    expect(groupCitations([])).toEqual([]);
  });
});
