import { describe, expect, it } from "vitest";
import { UNKNOWN_TOOL_LABEL, appendProgress, progressLabel } from "./assistant-progress";

describe("progressLabel", () => {
  it("도구 이름을 사람이 읽는 문구로 바꾼다", () => {
    expect(progressLabel("searching", "search_documents")).toBe("단지 문서 검색");
    expect(progressLabel("searching", "get_fees")).toBe("관리비 내역 확인");
  });

  it("도구가 없으면 단계 문구를 쓴다", () => {
    expect(progressLabel("searching", null)).toBe("근거 검색");
    expect(progressLabel("generating", null)).toBe("답변 작성");
    expect(progressLabel("verifying", null)).toBe("출처 확인");
  });

  it("매핑에 없는 도구는 일반 문구로 떨어진다", () => {
    expect(progressLabel("searching", "brand_new_tool")).toBe(UNKNOWN_TOOL_LABEL);
  });

  it("도구가 있으면 단계보다 도구가 우선이다(더 구체적)", () => {
    expect(progressLabel("generating", "get_fees")).toBe("관리비 내역 확인");
  });
});

describe("appendProgress", () => {
  it("단계를 순서대로 쌓는다", () => {
    // Arrange
    const steps: string[] = [];

    // Act
    const a = appendProgress(steps, "searching", null);
    const b = appendProgress(a, "searching", "get_fees");
    const c = appendProgress(b, "generating", null);

    // Assert
    expect(c).toEqual(["근거 검색", "관리비 내역 확인", "답변 작성"]);
  });

  it("같은 라벨이 연달아 오면 합친다", () => {
    const steps = appendProgress(["근거 검색"], "searching", null);
    expect(steps).toEqual(["근거 검색"]);
  });

  it("떨어져 있으면 같은 라벨도 다시 쌓는다(2회 조회는 2단계)", () => {
    const steps = appendProgress(["관리비 내역 확인", "답변 작성"], "searching", "get_fees");
    expect(steps).toEqual(["관리비 내역 확인", "답변 작성", "관리비 내역 확인"]);
  });

  it("입력 배열을 변형하지 않는다", () => {
    // Arrange
    const original = ["근거 검색"];

    // Act
    appendProgress(original, "generating", null);

    // Assert
    expect(original).toEqual(["근거 검색"]);
  });
});
