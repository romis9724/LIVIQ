import { describe, expect, it } from "vitest";
import { visibleSuggestions } from "./suggestions";

const NO_CTA = { inquiry: false, parking: false };

describe("visibleSuggestions — CTA 중복 제거", () => {
  it("CTA 가 없으면 서버 제안을 그대로 칩으로 낸다", () => {
    expect(visibleSuggestions(["지난달과 비교하기", "원문 문서 열어보기"], NO_CTA)).toEqual([
      "지난달과 비교하기",
      "원문 문서 열어보기",
    ]);
  });

  it("민원 접수 CTA 가 떠 있으면 같은 제안 칩은 지운다", () => {
    // Arrange — search_similar_inquiries 로 답한 케이스
    const suggestions = ["민원 접수하기", "내 민원 진행 상황 보기"];

    // Act
    const chips = visibleSuggestions(suggestions, { inquiry: true, parking: false });

    // Assert — 폼을 여는 딥링크(CTA)가 이기고 칩은 사라진다
    expect(chips).toEqual(["내 민원 진행 상황 보기"]);
  });

  it("주차맵 CTA 가 떠 있으면 같은 제안 칩은 지운다", () => {
    const chips = visibleSuggestions(["주차맵에서 보기"], { inquiry: false, parking: true });
    expect(chips).toEqual([]);
  });

  it("CTA 두 개가 다 떠 있으면 둘 다 지운다", () => {
    const chips = visibleSuggestions(["민원 접수하기", "주차맵에서 보기", "지난달과 비교하기"], {
      inquiry: true,
      parking: true,
    });
    expect(chips).toEqual(["지난달과 비교하기"]);
  });

  it("중복 문구는 한 번만 남긴다", () => {
    expect(visibleSuggestions(["민원 접수하기", "민원 접수하기"], NO_CTA)).toEqual([
      "민원 접수하기",
    ]);
  });

  it("제안이 비면 빈 배열(칩을 렌더하지 않는다)", () => {
    expect(visibleSuggestions([], { inquiry: true, parking: true })).toEqual([]);
  });
});
