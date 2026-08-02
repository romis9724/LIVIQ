import { describe, expect, it } from "vitest";
import type { AssistantCitation } from "./assistant-events";
import { structuredBlocks, toStructured } from "./assistant-structured";

/** 서버(ai_core/tools/library.py `_fee_data`)가 실제로 보내는 형태. */
const FEE_PAYLOAD = {
  kind: "fee_table",
  period: "2026-07",
  rows: [
    { name: "일반관리비", amount: 63000 },
    { name: "청소비", amount: 21000 },
  ],
  total: 84000,
  prev_total: 90000,
  diff: -6000,
};

describe("toStructured — kind 분기", () => {
  it("fee_table 을 표 데이터로 좁힌다(값 그대로)", () => {
    const data = toStructured(FEE_PAYLOAD);
    expect(data).toEqual({
      kind: "fee_table",
      period: "2026-07",
      rows: [
        { name: "일반관리비", amount: 63000 },
        { name: "청소비", amount: 21000 },
      ],
      total: 84000,
      prevTotal: 90000,
      diff: -6000,
      months: [],
      averageTotal: null,
      missingPeriods: [],
      excludedPeriods: [],
    });
  });

  it("여러 달 payload 는 months·평균으로 좁힌다(서버가 확정한 값 그대로)", () => {
    // Arrange — ai_core/tools/library.py `_fee_months_data`
    const raw = {
      kind: "fee_table",
      period: "2026-06, 2026-07",
      rows: [],
      total: null,
      prev_total: null,
      diff: null,
      months: [
        { period: "2026-06", total: 100000 },
        { period: "2026-07", total: 120000 },
      ],
      average_total: 110000,
      missing_periods: [],
      excluded_periods: ["2026-05"],
    };

    // Act
    const data = toStructured(raw);

    // Assert
    expect(data).toMatchObject({
      total: null,
      months: [
        { period: "2026-06", total: 100000 },
        { period: "2026-07", total: 120000 },
      ],
      averageTotal: 110000,
      excludedPeriods: ["2026-05"],
    });
  });

  it("평균을 못 낸 달이 있으면 averageTotal 은 null 이다(프론트가 대신 나누지 않는다)", () => {
    const data = toStructured({
      kind: "fee_table",
      months: [{ period: "2026-07", total: 120000 }],
      average_total: null,
      missing_periods: ["2026-06"],
    });
    expect(data).toMatchObject({ averageTotal: null, missingPeriods: ["2026-06"] });
  });

  it("전월 값이 없으면 null 로 남긴다(프론트가 0 으로 채우지 않는다)", () => {
    const data = toStructured({ ...FEE_PAYLOAD, prev_total: null, diff: null });
    expect(data).toMatchObject({ prevTotal: null, diff: null });
  });

  it("parking_spots 를 자리 목록으로 좁힌다", () => {
    // Arrange — ai_core/tools/parking.py `_data`
    const raw = {
      kind: "parking_spots",
      spots: [{ no: "012", kind: "일반", distance_m: 34 }],
    };

    // Act
    const data = toStructured(raw);

    // Assert
    expect(data).toEqual({
      kind: "parking_spots",
      spots: [{ no: "012", kind: "일반", distanceM: 34 }],
    });
  });

  it("facility_status 의 상태 카운트를 순서 있는 목록으로 편다", () => {
    // Arrange — ai_core/tools/library.py `_facility_data`
    const raw = {
      kind: "facility_status",
      total: 37,
      status_counts: { normal: 35, repair: 2 },
      items: [{ name: "101동 승강기", status: "normal", code: "EL-401-01" }],
    };

    // Act
    const data = toStructured(raw);

    // Assert
    expect(data).toEqual({
      kind: "facility_status",
      total: 37,
      statusCounts: [
        { status: "normal", count: 35 },
        { status: "repair", count: 2 },
      ],
      items: [{ name: "101동 승강기", status: "normal", code: "EL-401-01" }],
    });
  });

  it("inquiry_cases 를 사례 목록으로 좁힌다", () => {
    // Arrange — ai_core/tools/inquiries.py `_data`
    const raw = {
      kind: "inquiry_cases",
      cases: [
        {
          title: "온수가 미지근합니다",
          category: "설비",
          status: "완료",
          resolution: "온수 배관 밸브 조정 완료",
          is_mine: false,
        },
      ],
    };

    // Act
    const data = toStructured(raw);

    // Assert
    expect(data).toEqual({
      kind: "inquiry_cases",
      cases: [
        {
          title: "온수가 미지근합니다",
          category: "설비",
          status: "완료",
          resolution: "온수 배관 밸브 조정 완료",
          isMine: false,
        },
      ],
    });
  });

  it("모르는 kind·빈 값은 null(전방 호환 — 텍스트 인용만 남는다)", () => {
    expect(toStructured({ kind: "future_block", rows: [] })).toBeNull();
    expect(toStructured(null)).toBeNull();
    expect(toStructured(undefined)).toBeNull();
    expect(toStructured("nope")).toBeNull();
    expect(toStructured([1, 2])).toBeNull();
  });

  it("필드가 빠져도 던지지 않는다(와이어 JSON 은 신뢰하지 않는다)", () => {
    expect(toStructured({ kind: "parking_spots" })).toEqual({
      kind: "parking_spots",
      spots: [],
    });
    expect(toStructured({ kind: "fee_table", rows: ["nope", { name: "청소비" }] })).toMatchObject({
      rows: [{ name: "청소비", amount: 0 }],
      total: null,
      months: [],
      missingPeriods: [],
    });
  });
});

describe("structuredBlocks", () => {
  const citation = (ref: number, data: unknown): AssistantCitation => ({
    ref,
    documentId: null,
    documentTitle: "관리비 2026-07 확정 데이터",
    quote: "합계 84,000원",
    page: null,
    clause: null,
    data,
  });

  it("data 가 있는 인용만 블록으로 뽑고 ref 를 유지한다", () => {
    // Arrange — 문서 인용(data null) + 도구 카드(data 있음) + 모르는 kind
    const citations: AssistantCitation[] = [
      { ...citation(1, null), documentId: "d1", documentTitle: "관리규약" },
      citation(2, FEE_PAYLOAD),
      citation(3, { kind: "future_block" }),
    ];

    // Act
    const blocks = structuredBlocks(citations);

    // Assert
    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.ref).toBe(2);
    expect(blocks[0]?.data.kind).toBe("fee_table");
  });

  it("인용이 없으면 빈 배열", () => {
    expect(structuredBlocks([])).toEqual([]);
  });
});
