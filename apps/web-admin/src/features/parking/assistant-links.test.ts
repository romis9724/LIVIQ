import { describe, expect, it } from "vitest";
import type { AssistantCitation } from "@liviq/ui";
import {
  buildLongtermParkingHref,
  isLongtermParkingAnswer,
  longtermSpotNos,
  readSpotParam,
  readViewParam,
} from "./assistant-links";

function citation(overrides: Partial<AssistantCitation>): AssistantCitation {
  return {
    ref: 1,
    documentId: null,
    documentTitle: "외부 차량 장기주차",
    quote: "",
    page: null,
    clause: null,
    data: null,
    ...overrides,
  };
}

describe("longtermSpotNos", () => {
  it("장기주차 카드 quote 에서 면 번호를 오래된 순으로 뽑는다", () => {
    // Arrange — ai_core `_find_longterm_parking` 실제 quote 형태
    const quote =
      "24시간 이상 주차된 외부 차량 3대(오래된 순):\n- 098면 (31시간 경과)\n- 101면 (28시간 경과)\n- 095면 (25시간 경과)";

    // Act & Assert
    expect(longtermSpotNos([citation({ quote })])).toEqual(["098", "101", "095"]);
  });

  it("0건 quote·문서 인용에서는 빈 배열", () => {
    expect(longtermSpotNos([citation({ quote: "24시간 이상 주차된 외부 차량이 없습니다." })])).toEqual([]);
    expect(
      longtermSpotNos([citation({ documentId: "d1", documentTitle: "관리규약", quote: "098면" })]),
    ).toEqual([]);
  });
});

describe("buildLongtermParkingHref · 파라미터 읽기", () => {
  it("면 목록 → 3D 딥링크", () => {
    expect(buildLongtermParkingHref(["098", "101"])).toBe("/parking?spot=098,101&view=3d");
  });

  it("이상한 면 번호는 버린다(URL 미신뢰)", () => {
    expect(readSpotParam(new URLSearchParams("spot=098,<x>,101"))).toEqual(["098", "101"]);
    expect(readViewParam(new URLSearchParams("view=3d"))).toBe("3d");
    expect(readViewParam(new URLSearchParams("view=nope"))).toBe("2d");
  });
});

describe("isLongtermParkingAnswer", () => {
  it("find_longterm_parking 이 toolPath 에 있으면 CTA 대상", () => {
    expect(isLongtermParkingAnswer(["find_longterm_parking"])).toBe(true);
    expect(isLongtermParkingAnswer(["get_fees"])).toBe(false);
    expect(isLongtermParkingAnswer(undefined)).toBe(false);
  });
});
