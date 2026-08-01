import { describe, expect, it } from "vitest";
import type { Citation } from "@/features/assistant/api";
import {
  FLOOR_PLAN_CARD_TITLE,
  FLOOR_PLAN_TOOL,
  buildFloorPlanHref,
  deviceLabelsFromCitations,
  isFloorPlanAnswer,
  readDeviceParam,
} from "./links";

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    ref: 1,
    documentId: null,
    documentTitle: FLOOR_PLAN_CARD_TITLE,
    quote: "거실 콘센트 3곳: 위쪽·왼쪽·오른쪽; 주방 콘센트 1곳: 아래쪽",
    page: null,
    clause: null,
    data: null,
    ...overrides,
  };
}

describe("deviceLabelsFromCitations", () => {
  it("extracts the room+device labels from the floor plan tool card quote", () => {
    expect(deviceLabelsFromCitations([citation()])).toEqual(["거실 콘센트", "주방 콘센트"]);
  });

  it("keeps multi-word device types intact", () => {
    const card = citation({ quote: "안방 조명 스위치 2곳: 왼쪽·오른쪽" });
    expect(deviceLabelsFromCitations([card])).toEqual(["안방 조명 스위치"]);
  });

  it("ignores document citations that merely mention 곳", () => {
    // Arrange — 문서 인용은 documentId 가 있다(도구 카드는 null).
    const doc = citation({
      ref: 2,
      documentId: "doc-1",
      documentTitle: "관리규약",
      quote: "지정 장소 3곳: 관리사무소·경비실·주차장",
    });

    // Act·Assert
    expect(deviceLabelsFromCitations([doc])).toEqual([]);
  });

  it("returns an empty list for a room answer (방 라벨은 마커가 아니다)", () => {
    expect(deviceLabelsFromCitations([citation({ quote: "안방 위치; 거실 위치" })])).toEqual([]);
  });

  it("returns an empty list when there is no citation at all", () => {
    expect(deviceLabelsFromCitations([])).toEqual([]);
  });
});

describe("isFloorPlanAnswer", () => {
  it("is true when the floor plan tool ran", () => {
    expect(isFloorPlanAnswer([FLOOR_PLAN_TOOL])).toBe(true);
    expect(isFloorPlanAnswer(["search_documents", FLOOR_PLAN_TOOL])).toBe(true);
  });

  it("is false for other tools or a missing tool path", () => {
    expect(isFloorPlanAnswer(["search_documents"])).toBe(false);
    expect(isFloorPlanAnswer([])).toBe(false);
    expect(isFloorPlanAnswer(undefined)).toBe(false);
  });
});

describe("buildFloorPlanHref", () => {
  it("encodes labels into the device query", () => {
    expect(buildFloorPlanHref(["거실 콘센트", "주방 콘센트"])).toBe(
      `/floor-plan?device=${encodeURIComponent("거실 콘센트")},${encodeURIComponent("주방 콘센트")}`,
    );
  });

  it("drops the query when nothing was located", () => {
    expect(buildFloorPlanHref([])).toBe("/floor-plan");
  });

  it("drops unsafe or overlong labels instead of putting them in the URL", () => {
    expect(buildFloorPlanHref(["<script>", "", "가".repeat(30)])).toBe("/floor-plan");
  });

  it("caps the number of highlighted labels", () => {
    const many = Array.from({ length: 12 }, (_, i) => `기기${i}`);
    expect(buildFloorPlanHref(many).split(",")).toHaveLength(5);
  });
});

describe("readDeviceParam", () => {
  it("parses a comma separated label list", () => {
    const params = new URLSearchParams(`device=${encodeURIComponent("거실 콘센트")},분전함`);
    expect(readDeviceParam(params)).toEqual(["거실 콘센트", "분전함"]);
  });

  it("returns an empty list when the param is absent", () => {
    expect(readDeviceParam(new URLSearchParams(""))).toEqual([]);
  });

  it("rejects unsafe values and duplicates (URL is untrusted input)", () => {
    const params = new URLSearchParams("device=콘센트, 콘센트 ,<img src=x>,");
    expect(readDeviceParam(params)).toEqual(["콘센트"]);
  });

  it("caps the number of highlighted labels", () => {
    const many = Array.from({ length: 12 }, (_, i) => `기기${i}`).join(",");
    expect(readDeviceParam(new URLSearchParams(`device=${many}`))).toHaveLength(5);
  });
});
