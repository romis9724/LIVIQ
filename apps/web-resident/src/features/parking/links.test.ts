import { describe, expect, it } from "vitest";
import type { Citation } from "@/features/assistant/api";
import {
  MY_VEHICLE_CARD_TITLE,
  MY_VEHICLE_TOOL,
  PARKING_CARD_TITLE,
  PARKING_TOOL,
  buildParkingHref,
  isParkingAnswer,
  readSpotParam,
  spotNosFromCitations,
} from "./links";

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    ref: 1,
    documentId: null,
    documentTitle: PARKING_CARD_TITLE,
    quote: "① 012면 (일반, 약 34m)\n② 034면 (전기차, 약 40m)\n(데모 데이터 · 출처: parking_vehicles 점유 현황)",
    page: null,
    clause: null,
    data: null,
    ...overrides,
  };
}

describe("spotNosFromCitations", () => {
  it("extracts spot numbers from the parking tool card quote", () => {
    expect(spotNosFromCitations([citation()])).toEqual(["012", "034"]);
  });

  it("ignores document citations that merely mention 면", () => {
    // Arrange — 문서 인용은 documentId 가 있다(도구 카드는 null).
    const doc = citation({
      ref: 2,
      documentId: "doc-1",
      documentTitle: "주차장 관리규약",
      quote: "지상 200면을 운영한다.",
    });

    // Act·Assert
    expect(spotNosFromCitations([doc])).toEqual([]);
  });

  it("returns an empty list when the tool found no free spot", () => {
    expect(spotNosFromCitations([citation({ quote: "가까운 빈 주차자리가 없습니다." })])).toEqual([]);
  });

  it("returns an empty list when there is no citation at all", () => {
    expect(spotNosFromCitations([])).toEqual([]);
  });

  it("extracts the spot from the my-vehicle card quote (H19-2)", () => {
    const card = citation({
      documentTitle: MY_VEHICLE_CARD_TITLE,
      quote:
        "내 차량 1대:\n- 아이오닉5: 012면 (3시간 전 입차 · 401동 승강기까지 약 12m)\n(데모 데이터 · 출처: parking_vehicles 등록·점유 현황)",
    });

    expect(spotNosFromCitations([card])).toEqual(["012"]);
  });

  it("returns an empty list when my vehicle is not parked", () => {
    const card = citation({
      documentTitle: MY_VEHICLE_CARD_TITLE,
      quote: "내 차량 1대:\n- 아이오닉5: 주차장에 없음(등록만 됨)",
    });

    expect(spotNosFromCitations([card])).toEqual([]);
  });
});

describe("isParkingAnswer", () => {
  it("is true for both parking tools", () => {
    expect(isParkingAnswer([PARKING_TOOL])).toBe(true);
    expect(isParkingAnswer(["search_documents", MY_VEHICLE_TOOL])).toBe(true);
  });

  it("is false for other tools or a missing tool path", () => {
    expect(isParkingAnswer(["search_documents"])).toBe(false);
    expect(isParkingAnswer([])).toBe(false);
    expect(isParkingAnswer(undefined)).toBe(false);
  });
});

describe("buildParkingHref", () => {
  it("joins spot numbers into the spot query", () => {
    expect(buildParkingHref(["012", "034"])).toBe("/parking?spot=012,034");
  });

  it("drops the query when nothing was recommended", () => {
    expect(buildParkingHref([])).toBe("/parking");
  });

  it("drops malformed spot numbers instead of putting them in the URL", () => {
    expect(buildParkingHref(["012", "<script>", ""])).toBe("/parking?spot=012");
  });
});

describe("readSpotParam", () => {
  it("parses a comma separated spot list", () => {
    expect(readSpotParam(new URLSearchParams("spot=012,034,056"))).toEqual(["012", "034", "056"]);
  });

  it("returns an empty list when the param is absent", () => {
    expect(readSpotParam(new URLSearchParams(""))).toEqual([]);
  });

  it("rejects unsafe values and duplicates (URL is untrusted input)", () => {
    const params = new URLSearchParams("spot=012, 012 ,<img src=x>,0123456789");
    expect(readSpotParam(params)).toEqual(["012"]);
  });

  it("caps the number of highlighted spots", () => {
    const many = Array.from({ length: 20 }, (_, i) => String(i).padStart(3, "0")).join(",");
    expect(readSpotParam(new URLSearchParams(`spot=${many}`))).toHaveLength(10);
  });
});
