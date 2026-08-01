import { describe, expect, it } from "vitest";
import {
  ariaLabel,
  deviceCategory,
  dirRotation,
  isHighlightedDevice,
  tableRows,
  toPercent,
} from "./floor-plan-data";
import type { FloorPlanViewerDevice } from "./FloorPlanViewer";

describe("deviceCategory", () => {
  it("알려진 device_type을 카테고리로 매핑한다", () => {
    expect(deviceCategory("콘센트")).toBe("electric");
    expect(deviceCategory("월패드")).toBe("network");
    expect(deviceCategory("보일러")).toBe("water_heat");
    expect(deviceCategory("소화기")).toBe("safety");
  });

  it("미지 device_type은 '기타'", () => {
    expect(deviceCategory("알수없는기기")).toBe("other");
  });
});

describe("toPercent", () => {
  it("픽셀 좌표를 컨테이너 대비 %로 변환한다", () => {
    expect(toPercent(461.5, 923)).toBeCloseTo(50, 5);
    expect(toPercent(0, 923)).toBe(0);
  });

  it("total이 0 이하이면 방어적으로 0을 반환한다", () => {
    expect(toPercent(10, 0)).toBe(0);
    expect(toPercent(10, -1)).toBe(0);
  });
});

describe("dirRotation", () => {
  it("8방위 문자열을 각도로 변환한다", () => {
    expect(dirRotation("up")).toBe(0);
    expect(dirRotation("Right")).toBe(90);
    expect(dirRotation("down")).toBe(180);
    expect(dirRotation("sw")).toBe(225);
  });

  it("숫자 문자열은 그대로 각도로 해석한다", () => {
    expect(dirRotation("45")).toBe(45);
  });

  it("null이거나 해석 불가면 null(화살표 미표시)", () => {
    expect(dirRotation(null)).toBeNull();
    expect(dirRotation("알수없음")).toBeNull();
  });
});

describe("ariaLabel", () => {
  it("방이 있으면 '방 종류' 형식", () => {
    expect(ariaLabel({ room: "거실", deviceType: "콘센트" })).toBe("거실 콘센트");
  });

  it("방이 없으면 종류만", () => {
    expect(ariaLabel({ room: null, deviceType: "콘센트" })).toBe("콘센트");
  });
});

describe("isHighlightedDevice", () => {
  const outlet = { room: "거실", deviceType: "콘센트", label: null };

  it("방 한정 라벨은 그 방만 강조한다('거실 콘센트' — 시각 실측으로 과잉 강조 정정)", () => {
    expect(isHighlightedDevice(outlet, ["거실 콘센트"])).toBe(true);
    expect(isHighlightedDevice({ ...outlet, room: "안방" }, ["거실 콘센트"])).toBe(false);
  });

  it("방 없는 라벨은 전 방을 강조한다('안방 콘센트' ⊃ '콘센트')", () => {
    expect(isHighlightedDevice(outlet, ["콘센트"])).toBe(true);
    expect(isHighlightedDevice({ ...outlet, room: "안방" }, ["콘센트"])).toBe(true);
  });

  it("종류가 라벨을 포함해도 강조한다('조명 스위치' ⊃ '스위치')", () => {
    expect(
      isHighlightedDevice({ room: null, deviceType: "조명 스위치", label: null }, ["스위치"]),
    ).toBe(true);
  });

  it("기기 이름(label)으로도 매칭한다", () => {
    expect(
      isHighlightedDevice({ room: "주방", deviceType: "콘센트", label: "냉장고용" }, ["냉장고용"]),
    ).toBe(true);
  });

  it("관련 없는 라벨·빈 라벨은 강조하지 않는다(동의어 해석은 서버 도구 몫)", () => {
    expect(isHighlightedDevice(outlet, ["보일러"])).toBe(false);
    expect(isHighlightedDevice(outlet, ["두꺼비집"])).toBe(false);
    expect(isHighlightedDevice(outlet, ["", "  "])).toBe(false);
    expect(isHighlightedDevice(outlet, [])).toBe(false);
  });
});

describe("tableRows", () => {
  const device = (over: Partial<FloorPlanViewerDevice>): FloorPlanViewerDevice => ({
    id: "d1",
    deviceType: "콘센트",
    x: 0,
    y: 0,
    room: null,
    dir: null,
    label: null,
    memo: null,
    ...over,
  });

  it("room 라벨 행은 제외한다", () => {
    const rows = tableRows([device({ deviceType: "room", room: "거실" }), device({ room: "안방" })]);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.room).toBe("안방");
  });

  it("room·memo 없으면 '-'로 표기하고 label 있으면 종류에 괄호로 덧붙인다", () => {
    const rows = tableRows([device({ label: "냉장고용", memo: "누전 주의" })]);
    expect(rows[0]).toEqual({ room: "-", type: "콘센트(냉장고용)", note: "누전 주의" });
  });
});
