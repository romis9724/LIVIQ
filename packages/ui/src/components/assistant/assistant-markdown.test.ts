import { describe, expect, it } from "vitest";
import { answerBlocks, stripMarkers } from "./assistant-markdown";

describe("stripMarkers", () => {
  it("굵게·기울임·코드 기호를 표시에서 벗긴다", () => {
    expect(stripMarkers("**관리비**는 *매월* 부과됩니다")).toBe("관리비는 매월 부과됩니다");
  });

  it("제목 기호를 벗기고 본문은 남긴다", () => {
    expect(stripMarkers("## 납부 기한")).toBe("납부 기한");
  });

  it("마스킹된 이름의 별표는 건드리지 않는다", () => {
    // 김*수 는 마스킹 표기지 강조가 아니다 — 벗기면 개인정보 표시가 훼손된다.
    expect(stripMarkers("담당자는 김*수 소장입니다")).toBe("담당자는 김*수 소장입니다");
  });

  it("프롬프트 내부 섹션 라벨 에코를 표시에서 벗긴다", () => {
    expect(stripMarkers("[확정 데이터·도구 결과] 이번 달 관리비는 176,601원입니다.")).toBe(
      "이번 달 관리비는 176,601원입니다.",
    );
    expect(stripMarkers("[문서 근거] 임기는 2년입니다 [1]")).toBe("임기는 2년입니다");
    // 텍스트 대괄호([별관] 등)는 남는다 — 내부 라벨만 매치.
    expect(stripMarkers("[별관] 이용 안내")).toBe("[별관] 이용 안내");
  });

  it("별표 연속(마스킹 자릿수)에도 걸리지 않는다", () => {
    expect(stripMarkers("연락처 010-****-5678")).toBe("연락처 010-****-5678");
  });

  it("인용 마커를 표시에서 벗긴다 — 출처는 SourceStrip 카드가 보여준다(사용자 지적)", () => {
    expect(stripMarkers("관리규약 제5조에 따릅니다 [2]")).toBe("관리규약 제5조에 따릅니다");
    expect(stripMarkers("7월 1일 점검합니다. [1][3]")).toBe("7월 1일 점검합니다.");
    expect(stripMarkers("납부기한은 8월 31일입니다 [1, 2]")).toBe("납부기한은 8월 31일입니다");
  });

  it("숫자 아닌 대괄호 텍스트는 남긴다", () => {
    expect(stripMarkers("[별관] 이용 안내")).toBe("[별관] 이용 안내");
  });

  it("스트리밍 중 미완성 마커는 건드리지 않는다", () => {
    expect(stripMarkers("점검합니다. [1")).toBe("점검합니다. [1");
  });
});

describe("answerBlocks", () => {
  it("글머리 줄 연속을 하나의 목록으로 묶는다", () => {
    // Arrange
    const text = "납부 항목은 다음과 같습니다 [1]\n- 일반관리비\n- 청소비\n- 승강기유지비";

    // Act
    const blocks = answerBlocks(text);

    // Assert
    expect(blocks).toEqual([
      { kind: "p", text: "납부 항목은 다음과 같습니다" },
      { kind: "ul", items: ["일반관리비", "청소비", "승강기유지비"] },
    ]);
  });

  it("모델이 `- ` 대신 `*`·`•` 를 써도 목록으로 본다", () => {
    expect(answerBlocks("* 첫째\n• 둘째")).toEqual([{ kind: "ul", items: ["첫째", "둘째"] }]);
  });

  it("목록 항목 안의 강조 기호도 벗긴다", () => {
    expect(answerBlocks("- **일반관리비**: 12,000원")).toEqual([
      { kind: "ul", items: ["일반관리비: 12,000원"] },
    ]);
  });

  it("빈 줄은 문단 경계다", () => {
    expect(answerBlocks("첫 문단\n이어지는 줄\n\n둘째 문단")).toEqual([
      { kind: "p", text: "첫 문단\n이어지는 줄" },
      { kind: "p", text: "둘째 문단" },
    ]);
  });

  it("목록 뒤 문단이 이어져도 순서를 지킨다", () => {
    expect(answerBlocks("- 항목\n마무리 문장 [1]")).toEqual([
      { kind: "ul", items: ["항목"] },
      { kind: "p", text: "마무리 문장" },
    ]);
  });

  it("빈 문자열은 블록 0개", () => {
    expect(answerBlocks("")).toEqual([]);
    expect(answerBlocks("   \n\n  ")).toEqual([]);
  });

  it("스트리밍 중 짝이 안 맞는 기호는 그대로 남긴다(다음 청크에서 완성)", () => {
    expect(answerBlocks("관리비는 **12,0")).toEqual([{ kind: "p", text: "관리비는 **12,0" }]);
  });
});
