import { describe, expect, it } from "vitest";
import type { AssistantCitation } from "@liviq/ui";
import {
  buildTwinHouseholdHref,
  householdDeviceTarget,
  isHouseholdDevicesAnswer,
  readDeviceParam,
  readUnitParams,
} from "./assistant-links";

/** ai_core `_find_household_devices` 가 싣는 실제 카드 형태(data = 서버 확정값). */
function citation(overrides: Partial<AssistantCitation> = {}): AssistantCitation {
  return {
    ref: 1,
    documentId: null,
    documentTitle: "세대 평면도 위치",
    quote: "402동 201호 · 현관 분전함 1곳: 왼쪽",
    page: null,
    clause: null,
    data: { kind: "home_devices", dong: "402", ho: 201, labels: ["현관 분전함"] },
    ...overrides,
  };
}

describe("isHouseholdDevicesAnswer", () => {
  it("도구가 호출된 답변에서만 참", () => {
    expect(isHouseholdDevicesAnswer(["find_household_devices"])).toBe(true);
    expect(isHouseholdDevicesAnswer(["get_facilities"])).toBe(false);
    expect(isHouseholdDevicesAnswer(undefined)).toBe(false);
  });
});

describe("householdDeviceTarget", () => {
  it("도구 카드 data 에서 동·호수·강조 라벨을 뽑는다", () => {
    expect(householdDeviceTarget([citation()])).toEqual({
      dong: "402",
      ho: 201,
      labels: ["현관 분전함"],
    });
  });

  it("문서 인용·다른 kind·data 없음은 무시한다", () => {
    expect(householdDeviceTarget([citation({ documentId: "d1", documentTitle: "관리규약" })])).toBeNull();
    expect(householdDeviceTarget([citation({ data: { kind: "facility_status" } })])).toBeNull();
    expect(householdDeviceTarget([citation({ data: null })])).toBeNull();
    expect(householdDeviceTarget([])).toBeNull();
  });

  it("동·호수 형식이 어긋나면 null — 화면 이동 대상이 불확실하면 CTA 를 띄우지 않는다", () => {
    expect(
      householdDeviceTarget([citation({ data: { kind: "home_devices", dong: "402동", ho: 201 } })]),
    ).toBeNull();
    expect(
      householdDeviceTarget([citation({ data: { kind: "home_devices", dong: "402", ho: "201" } })]),
    ).toBeNull();
    expect(
      householdDeviceTarget([citation({ data: { kind: "home_devices", dong: "402", ho: 0 } })]),
    ).toBeNull();
  });

  it("라벨은 개수·문자를 검증하고 중복을 제거한다", () => {
    const data = {
      kind: "home_devices",
      dong: "402",
      ho: 201,
      labels: ["거실 콘센트", "거실 콘센트", "<script>", 7, "주방 콘센트"],
    };

    expect(householdDeviceTarget([citation({ data })])?.labels).toEqual([
      "거실 콘센트",
      "주방 콘센트",
    ]);
  });
});

describe("buildTwinHouseholdHref", () => {
  it("세대 + 강조 라벨을 쿼리스트링으로 싣는다", () => {
    const href = buildTwinHouseholdHref({ dong: "402", ho: 201, labels: ["현관 분전함"] });

    expect(href).toBe("/twin?dong=402&ho=201&device=%ED%98%84%EA%B4%80+%EB%B6%84%EC%A0%84%ED%95%A8");
  });

  it("라벨이 없으면 세대만 연다", () => {
    expect(buildTwinHouseholdHref({ dong: "402", ho: 201, labels: [] })).toBe("/twin?dong=402&ho=201");
  });
});

describe("readUnitParams · readDeviceParam", () => {
  const params = (query: string) => new URLSearchParams(query);

  it("왕복(build → read)이 같은 값을 준다", () => {
    const target = { dong: "402", ho: 201, labels: ["현관 분전함", "거실 콘센트"] };
    const search = params(buildTwinHouseholdHref(target).split("?")[1] as string);

    expect(readUnitParams(search)).toEqual({ dong: "402", ho: 201 });
    expect(readDeviceParam(search)).toEqual(target.labels);
  });

  it("URL 은 신뢰하지 않는다 — 형식이 어긋나면 딥링크 없음", () => {
    expect(readUnitParams(params(""))).toBeNull();
    expect(readUnitParams(params("dong=402"))).toBeNull();
    expect(readUnitParams(params("dong=abc&ho=201"))).toBeNull();
    expect(readUnitParams(params("dong=402&ho=-1"))).toBeNull();
    expect(readDeviceParam(params("device=%3Cscript%3E"))).toEqual([]);
  });
});
