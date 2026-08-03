import { describe, it, expect } from "vitest";

import type { GraphLink, GraphNode, GraphNodeLabel, Inquiry, InquiryStatus } from "@/lib/api";
import {
  SYSTEM_COLOR_VARS,
  UNCLASSIFIED,
  UNCLASSIFIED_COLOR_VAR,
  UNLOCATED,
  INCIDENT_OPEN_COLOR_VAR,
  INCIDENT_RESOLVED_COLOR_VAR,
  MAINTENANCE_COLOR_VAR,
  LOCATION_COLOR_VAR,
  FLOOR_PLAN_COLOR_VAR,
  PLAN_ROOM_COLOR_VAR,
  PLAN_KIND_COLOR_VAR,
  PLAN_DEVICE_COLOR_VAR,
  COMPLEX_COLOR_VAR,
  NODE_VAL_FACILITY,
  NODE_VAL_EVENT,
  NODE_VAL_LOCATION,
  NODE_VAL_FLOOR_PLAN,
  NODE_VAL_PLAN_HUB,
  NODE_VAL_PLAN_DEVICE,
  NODE_VAL_COMPLEX,
  buildingToken,
  centerByNodeId,
  complexSummary,
  estimatedInquiries,
  facilitiesAtLocation,
  facilityIdForNode,
  findFacilityByName,
  groupCenters,
  lensColorVar,
  lensGroupByNodeId,
  lensGroups,
  lensNodeColorVar,
  locationOf,
  matchesBuilding,
  nodeBaseVal,
  nodeColorVar,
  searchFacilities,
  systemByNodeId,
  systemColorVar,
  systemGroups,
  systemOf,
} from "./graph-data";

function facilityNode(pgId: string, overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    pgId,
    label: "facility",
    code: null,
    name: `설비 ${pgId}`,
    type: "승강기",
    location: null,
    status: "normal",
    at: null,
    resolved: null,
    ...overrides,
  };
}

function incidentNode(pgId: string, resolved: boolean): GraphNode {
  return {
    pgId,
    label: "incident",
    code: null,
    name: "이상 소음",
    type: null,
    location: null,
    status: null,
    at: "2026-07-01T00:00:00Z",
    resolved,
  };
}

function maintenanceNode(pgId: string): GraphNode {
  return {
    pgId,
    label: "maintenance",
    code: null,
    name: "정기 점검",
    type: null,
    location: null,
    status: null,
    at: "2026-07-02T00:00:00Z",
    resolved: null,
  };
}

function locationNode(pgId: string, name: string): GraphNode {
  return {
    pgId,
    label: "location",
    code: null,
    name,
    type: null,
    location: null,
    status: null,
    at: null,
    resolved: null,
  };
}

function floorPlanNode(pgId: string, name: string): GraphNode {
  return {
    pgId,
    label: "floor_plan",
    code: null,
    name,
    type: null,
    location: null,
    status: null,
    at: null,
    resolved: null,
  };
}

function complexNode(pgId: string, name: string): GraphNode {
  return {
    pgId,
    label: "complex",
    code: null,
    name,
    type: null,
    location: null,
    status: null,
    at: null,
    resolved: null,
  };
}

/** 도면 하위 계층 노드(방·종류 허브·마커 — H14-1). */
function planNode(pgId: string, label: GraphNodeLabel, name: string): GraphNode {
  return {
    pgId,
    label,
    code: null,
    name,
    type: null,
    location: null,
    status: null,
    at: null,
    resolved: null,
  };
}

function inquiry(overrides: Partial<Inquiry> = {}): Inquiry {
  return {
    id: "i-1",
    title: "누수",
    body: "천장에서 물이 샙니다",
    status: "received" as InquiryStatus,
    priority: null,
    categoryCodeId: null,
    assigneeUserId: null,
    authorUserId: "u-1",
    createdAt: "2026-07-20T00:00:00Z",
    updatedAt: "2026-07-20T00:00:00Z",
    facilityId: null,
    facilityName: null,
    ...overrides,
  };
}

describe("systemOf", () => {
  it("type 이 있으면 그 값을 계통으로 쓴다", () => {
    expect(systemOf(facilityNode("f1", { type: "소방" }))).toBe("소방");
  });

  it("type 이 null 이면 '미분류'다", () => {
    expect(systemOf(facilityNode("f1", { type: null }))).toBe(UNCLASSIFIED);
  });

  it("type 이 공백만이면 '미분류'다", () => {
    expect(systemOf(facilityNode("f1", { type: "   " }))).toBe(UNCLASSIFIED);
  });
});

describe("systemGroups", () => {
  it("시설 노드의 계통만 중복 없이 모은다(이력 노드는 제외)", () => {
    const nodes = [
      facilityNode("f1", { type: "승강기" }),
      facilityNode("f2", { type: "소방" }),
      facilityNode("f3", { type: "승강기" }),
      incidentNode("i1", false),
      maintenanceNode("m1"),
    ];

    expect(systemGroups(nodes)).toEqual(["소방", "승강기"]);
  });

  it("'미분류'는 항상 마지막에 온다", () => {
    const nodes = [
      facilityNode("f1", { type: null }),
      facilityNode("f2", { type: "전기" }),
      facilityNode("f3", { type: "급배수" }),
    ];

    expect(systemGroups(nodes)).toEqual(["급배수", "전기", UNCLASSIFIED]);
  });

  it("시설이 없으면 빈 배열", () => {
    expect(systemGroups([incidentNode("i1", true)])).toEqual([]);
  });
});

describe("systemByNodeId", () => {
  it("장애·정비 노드는 링크 source 시설의 계통을 물려받는다", () => {
    const nodes = [
      facilityNode("f1", { type: "승강기" }),
      incidentNode("i1", false),
      maintenanceNode("m1"),
    ];
    const links: GraphLink[] = [
      { source: "f1", target: "i1", kind: "HAS_INCIDENT" },
      { source: "f1", target: "m1", kind: "HAS_MAINTENANCE" },
    ];

    const byId = systemByNodeId(nodes, links);

    expect(byId.get("f1")).toBe("승강기");
    expect(byId.get("i1")).toBe("승강기");
    expect(byId.get("m1")).toBe("승강기");
  });

  it("링크가 없는 고아 이력 노드는 계통이 없다(degraded 폴백 포함)", () => {
    const byId = systemByNodeId([facilityNode("f1"), incidentNode("i1", false)], []);

    expect(byId.has("i1")).toBe(false);
  });

  it("location 노드는 LOCATED_IN 으로 연결돼도 계통을 물려받지 않는다(여러 계통 공유 — H13-7)", () => {
    const nodes = [facilityNode("f1", { type: "승강기" }), locationNode("401동", "401동")];
    const links: GraphLink[] = [{ source: "f1", target: "401동", kind: "LOCATED_IN" }];

    const byId = systemByNodeId(nodes, links);

    expect(byId.has("401동")).toBe(false);
  });

  it("complex 노드는 PART_OF 로 연결돼도 계통을 물려받지 않는다(tenant당 1개 허브 — H13-7 확장)", () => {
    const nodes = [
      facilityNode("f1", { type: "승강기" }),
      locationNode("401동", "401동"),
      complexNode("c1", "첫마을"),
    ];
    const links: GraphLink[] = [
      { source: "f1", target: "401동", kind: "LOCATED_IN" },
      { source: "401동", target: "c1", kind: "PART_OF" },
    ];

    const byId = systemByNodeId(nodes, links);

    expect(byId.has("c1")).toBe(false);
  });
});

describe("systemColorVar", () => {
  it("계통 순서대로 팔레트 변수를 배정한다", () => {
    const groups = ["급배수", "전기"];

    expect(systemColorVar("급배수", groups)).toBe(SYSTEM_COLOR_VARS[0]);
    expect(systemColorVar("전기", groups)).toBe(SYSTEM_COLOR_VARS[1]);
  });

  it("'미분류'는 중립 변수를 쓴다", () => {
    expect(systemColorVar(UNCLASSIFIED, [UNCLASSIFIED])).toBe(UNCLASSIFIED_COLOR_VAR);
  });

  it("팔레트를 넘어서는 계통은 순환한다", () => {
    const groups = Array.from({ length: SYSTEM_COLOR_VARS.length + 1 }, (_, i) => `계통${i}`);

    expect(systemColorVar(groups[SYSTEM_COLOR_VARS.length]!, groups)).toBe(SYSTEM_COLOR_VARS[0]);
  });

  it("목록에 없는 계통은 중립 변수로 떨어진다", () => {
    expect(systemColorVar("없는계통", ["전기"])).toBe(UNCLASSIFIED_COLOR_VAR);
  });
});

describe("nodeColorVar", () => {
  const nodes = [facilityNode("f1", { type: "전기" }), incidentNode("i1", false)];
  const links: GraphLink[] = [{ source: "f1", target: "i1", kind: "HAS_INCIDENT" }];
  const groups = systemGroups(nodes);
  const systemById = systemByNodeId(nodes, links);

  it("시설 노드는 계통색", () => {
    expect(nodeColorVar(nodes[0]!, systemById, groups)).toBe(SYSTEM_COLOR_VARS[0]);
  });

  it("미해결 장애는 경고색", () => {
    expect(nodeColorVar(incidentNode("i1", false), systemById, groups)).toBe(
      INCIDENT_OPEN_COLOR_VAR,
    );
  });

  it("조치된 장애는 완화색", () => {
    expect(nodeColorVar(incidentNode("i1", true), systemById, groups)).toBe(
      INCIDENT_RESOLVED_COLOR_VAR,
    );
  });

  it("정비는 중립색", () => {
    expect(nodeColorVar(maintenanceNode("m1"), systemById, groups)).toBe(MAINTENANCE_COLOR_VAR);
  });
});

describe("groupCenters", () => {
  it("계통이 1개 이하면 원점에 둔다(퍼뜨릴 이유가 없다)", () => {
    expect(groupCenters(["전기"]).get("전기")).toEqual({ x: 0, y: 0, z: 0 });
    expect(groupCenters([]).size).toBe(0);
  });

  it("계통이 여럿이면 반지름 위 서로 다른 지점에 배치한다", () => {
    const centers = groupCenters(["전기", "소방", "승강기"], 100);

    expect(centers.size).toBe(3);
    for (const center of centers.values()) {
      expect(Math.hypot(center.x, center.y)).toBeCloseTo(100, 6);
    }
    const keys = [...centers.keys()];
    expect(centers.get(keys[0]!)).not.toEqual(centers.get(keys[1]!));
  });
});

describe("centerByNodeId", () => {
  it("이력 노드도 부모 시설 계통의 중심을 따라간다", () => {
    const nodes = [facilityNode("f1", { type: "전기" }), incidentNode("i1", false)];
    const links: GraphLink[] = [{ source: "f1", target: "i1", kind: "HAS_INCIDENT" }];
    const groups = systemGroups(nodes);

    const byId = centerByNodeId(systemByNodeId(nodes, links), groupCenters(groups));

    expect(byId.get("i1")).toEqual(byId.get("f1"));
  });
});

describe("searchFacilities / findFacilityByName", () => {
  const nodes = [
    facilityNode("f1", { name: "101동 승강기" }),
    facilityNode("f2", { name: "102동 승강기" }),
    facilityNode("f3", { name: "지하 저수조" }),
    incidentNode("i1", false),
  ];

  it("부분일치로 시설만 찾는다", () => {
    expect(searchFacilities(nodes, "승강기").map((n) => n.pgId)).toEqual(["f1", "f2"]);
  });

  it("공백·대소문자를 무시한다", () => {
    expect(searchFacilities(nodes, " 101 동 ").map((n) => n.pgId)).toEqual(["f1"]);
  });

  it("빈 질의는 결과 없음", () => {
    expect(searchFacilities(nodes, "   ")).toEqual([]);
  });

  it("limit 을 넘지 않는다", () => {
    expect(searchFacilities(nodes, "승강기", 1)).toHaveLength(1);
  });

  it("완전일치를 부분일치보다 우선한다", () => {
    const withPrefix = [facilityNode("f9", { name: "101동 승강기 제어반" }), ...nodes];

    expect(findFacilityByName(withPrefix, "101동 승강기")?.pgId).toBe("f1");
  });

  it("일치가 없으면 null", () => {
    expect(findFacilityByName(nodes, "보일러")).toBeNull();
  });

  it("코드번호 완전일치로도 찾는다", () => {
    const coded = [facilityNode("f8", { name: "지하 저수조", code: "WS-000-01" }), ...nodes];

    expect(findFacilityByName(coded, "WS-000-01")?.pgId).toBe("f8");
    expect(findFacilityByName(coded, "ws-000-01")?.pgId).toBe("f8"); // 대소문자 무시
  });

  it("이름 완전일치를 코드 일치보다 우선한다", () => {
    const coded = [
      facilityNode("f8", { name: "101동 승강기", code: "지하 저수조" }),
      ...nodes,
    ];

    expect(findFacilityByName(coded, "지하 저수조")?.pgId).toBe("f3");
  });

  it("없는 코드는 null", () => {
    const coded = [facilityNode("f8", { name: "지하 저수조", code: "WS-000-01" }), ...nodes];

    expect(findFacilityByName(coded, "EL-999-99")).toBeNull();
  });
});

describe("buildingToken / matchesBuilding", () => {
  it("위치 문자열에서 동 번호를 뽑는다", () => {
    expect(buildingToken("401동 기계실")).toBe("401동");
    expect(buildingToken("401 동")).toBe("401동");
  });

  it("동 표기가 없으면 null(추정을 시작하지 않는다)", () => {
    expect(buildingToken("지하 주차장")).toBeNull();
    expect(buildingToken(null)).toBeNull();
  });

  it("공백을 무시하고 텍스트 포함 여부를 본다", () => {
    expect(matchesBuilding("401동", "401 동 엘리베이터가 멈췄어요")).toBe(true);
    expect(matchesBuilding("401동", "402동 엘리베이터가 멈췄어요")).toBe(false);
  });
});

describe("locationOf", () => {
  it("동 표기가 있으면 동 토큰", () => {
    expect(locationOf(facilityNode("f1", { location: "401동 기계실" }))).toBe("401동");
  });

  it("동 표기가 없거나 위치가 null 이면 '미지정'", () => {
    expect(locationOf(facilityNode("f1", { location: "지하 주차장" }))).toBe(UNLOCATED);
    expect(locationOf(facilityNode("f1", { location: null }))).toBe(UNLOCATED);
  });
});

describe("lensGroups", () => {
  const nodes = [
    facilityNode("f1", { type: "승강기", location: "101동" }),
    facilityNode("f2", { type: "소방", location: "102동" }),
    facilityNode("f3", { type: "승강기", location: null }),
    incidentNode("i1", false),
  ];

  it("system 렌즈는 systemGroups 와 같다", () => {
    expect(lensGroups("system", nodes)).toEqual(systemGroups(nodes));
  });

  it("location 렌즈는 동 토큰을 가나다 순으로 모으고 '미지정'은 마지막", () => {
    expect(lensGroups("location", nodes)).toEqual(["101동", "102동", UNLOCATED]);
  });
});

describe("lensGroupByNodeId", () => {
  const nodes = [facilityNode("f1", { type: "전기", location: "401동" }), incidentNode("i1", false)];
  const links: GraphLink[] = [{ source: "f1", target: "i1", kind: "HAS_INCIDENT" }];

  it("location 렌즈 — 이력 노드는 부모 시설의 동을 물려받는다", () => {
    const byId = lensGroupByNodeId("location", nodes, links);
    expect(byId.get("f1")).toBe("401동");
    expect(byId.get("i1")).toBe("401동");
  });

  it("location 렌즈 — location 노드도 연결 시설의 동을 물려받는다(H13-7 결정 3)", () => {
    const withLocation = [...nodes, locationNode("401동 기계실", "401동 기계실")];
    const withLink: GraphLink[] = [
      ...links,
      { source: "f1", target: "401동 기계실", kind: "LOCATED_IN" },
    ];

    const byId = lensGroupByNodeId("location", withLocation, withLink);

    expect(byId.get("401동 기계실")).toBe("401동");
  });

  it("location 렌즈 — floor_plan 은 그룹을 물려받지 않는다(고유색 고정)", () => {
    const withPlan = [...nodes, floorPlanNode("fp1", "84A")];
    const withLink: GraphLink[] = [...links, { source: "f1", target: "fp1", kind: "LINKED_TO" }];

    const byId = lensGroupByNodeId("location", withPlan, withLink);

    expect(byId.has("fp1")).toBe(false);
  });

  it("location 렌즈 — complex 는 PART_OF 로 연결돼도 그룹을 물려받지 않는다(고정색 — H13-7 확장)", () => {
    const withComplex = [...nodes, locationNode("401동", "401동"), complexNode("c1", "첫마을")];
    const withLink: GraphLink[] = [
      ...links,
      { source: "f1", target: "401동", kind: "LOCATED_IN" },
      { source: "401동", target: "c1", kind: "PART_OF" },
    ];

    const byId = lensGroupByNodeId("location", withComplex, withLink);

    expect(byId.has("c1")).toBe(false);
  });
});

describe("lensColorVar / lensNodeColorVar", () => {
  it("location 렌즈의 '미지정'은 중립 변수", () => {
    expect(lensColorVar("location", UNLOCATED, [UNLOCATED])).toBe(UNCLASSIFIED_COLOR_VAR);
  });

  it("location 렌즈의 동은 systemColorVar 와 같은 순환 팔레트를 쓴다", () => {
    const groups = ["101동", "102동"];
    expect(lensColorVar("location", "101동", groups)).toBe(SYSTEM_COLOR_VARS[0]);
  });

  it("장애·정비 노드는 렌즈와 무관하게 이력 색", () => {
    const groupById = new Map<string, string>();
    expect(lensNodeColorVar("location", incidentNode("i1", false), groupById, [])).toBe(
      INCIDENT_OPEN_COLOR_VAR,
    );
    expect(lensNodeColorVar("location", maintenanceNode("m1"), groupById, [])).toBe(
      MAINTENANCE_COLOR_VAR,
    );
  });

  it("floor_plan 은 렌즈·그룹과 무관하게 고유색(H13-7)", () => {
    const groupById = new Map<string, string>();
    expect(lensNodeColorVar("system", floorPlanNode("fp1", "84A"), groupById, [])).toBe(
      FLOOR_PLAN_COLOR_VAR,
    );
    expect(lensNodeColorVar("location", floorPlanNode("fp1", "84A"), groupById, ["401동"])).toBe(
      FLOOR_PLAN_COLOR_VAR,
    );
  });

  it("complex 는 렌즈·그룹과 무관하게 고유색(tenant당 1개 허브 — H13-7 확장)", () => {
    const groupById = new Map([["c1", "401동"]]); // 그룹이 있어도 무시돼야 한다
    expect(lensNodeColorVar("system", complexNode("c1", "첫마을"), groupById, [])).toBe(
      COMPLEX_COLOR_VAR,
    );
    expect(lensNodeColorVar("location", complexNode("c1", "첫마을"), groupById, ["401동"])).toBe(
      COMPLEX_COLOR_VAR,
    );
  });

  it("도면 하위 계층(방·종류·마커)은 렌즈·그룹과 무관하게 고유색(H14-1)", () => {
    const groupById = new Map([["r1", "401동"]]); // 그룹이 있어도 무시돼야 한다
    expect(lensNodeColorVar("system", planNode("r1", "plan_room", "거실"), groupById, [])).toBe(
      PLAN_ROOM_COLOR_VAR,
    );
    expect(
      lensNodeColorVar("location", planNode("k1", "plan_kind", "콘센트"), groupById, ["401동"]),
    ).toBe(PLAN_KIND_COLOR_VAR);
    expect(
      lensNodeColorVar("system", planNode("d1", "plan_device", "콘센트(거실)"), groupById, []),
    ).toBe(PLAN_DEVICE_COLOR_VAR);
  });

  it("location 노드 — 계통 렌즈에선 중립색(여러 계통이 공유하는 노드라 — H13-7 결정 3)", () => {
    const groupById = new Map<string, string>();
    expect(lensNodeColorVar("system", locationNode("401동", "401동"), groupById, ["전기"])).toBe(
      LOCATION_COLOR_VAR,
    );
  });

  it("location 노드 — 위치 렌즈에선 자기 그룹 중심색(H13-7 결정 3)", () => {
    const groups = ["401동", "402동"];
    const groupById = new Map([["401동", "401동"]]);
    expect(lensNodeColorVar("location", locationNode("401동", "401동"), groupById, groups)).toBe(
      SYSTEM_COLOR_VARS[0],
    );
  });
});

describe("nodeBaseVal", () => {
  it("라벨별 기준 크기 — 위치는 시설보다 크고 이력은 작다(H13-7)", () => {
    expect(nodeBaseVal("facility")).toBe(NODE_VAL_FACILITY);
    expect(nodeBaseVal("location")).toBeGreaterThan(NODE_VAL_FACILITY);
    expect(nodeBaseVal("incident")).toBe(NODE_VAL_EVENT);
    expect(nodeBaseVal("incident")).toBeLessThan(NODE_VAL_FACILITY);
    expect(nodeBaseVal("floor_plan")).toBe(NODE_VAL_FLOOR_PLAN);
    expect(nodeBaseVal("location")).toBe(NODE_VAL_LOCATION);
  });

  it("complex 는 가장 큰 크기다(tenant당 1개 최상위 허브 — H13-7 확장)", () => {
    expect(nodeBaseVal("complex")).toBe(NODE_VAL_COMPLEX);
    expect(nodeBaseVal("complex")).toBeGreaterThan(NODE_VAL_LOCATION);
  });

  it("도면 계층 — 방·종류 허브는 도면보다 작고 마커는 가장 작다(H14-1)", () => {
    expect(nodeBaseVal("plan_room")).toBe(NODE_VAL_PLAN_HUB);
    expect(nodeBaseVal("plan_kind")).toBe(NODE_VAL_PLAN_HUB);
    expect(nodeBaseVal("plan_device")).toBe(NODE_VAL_PLAN_DEVICE);
    expect(NODE_VAL_PLAN_HUB).toBeLessThan(NODE_VAL_FLOOR_PLAN);
    expect(NODE_VAL_PLAN_DEVICE).toBeLessThan(NODE_VAL_EVENT);
  });
});

describe("complexSummary", () => {
  it("설비·위치·도면·미해결 장애 개수를 센다(H14-1 현황 요약)", () => {
    const nodes = [
      facilityNode("f1"),
      facilityNode("f2"),
      locationNode("401동", "401동"),
      locationNode("402동", "402동"),
      incidentNode("i1", false),
      incidentNode("i2", true),
      floorPlanNode("fp1", "84A"),
      complexNode("c1", "첫마을"),
    ];

    expect(complexSummary(nodes)).toEqual({
      locationCount: 2,
      facilityCount: 2,
      floorPlanCount: 1,
      openIncidentCount: 1,
    });
  });

  it("노드가 단지뿐이면 전부 0", () => {
    expect(complexSummary([complexNode("c1", "첫마을")])).toEqual({
      locationCount: 0,
      facilityCount: 0,
      floorPlanCount: 0,
      openIncidentCount: 0,
    });
  });
});

describe("facilitiesAtLocation", () => {
  it("LOCATED_IN 으로 연결된 시설만 모은다(그래프 데이터 파생, 신규 API 없음)", () => {
    const nodes = [
      facilityNode("f1", { name: "101동 승강기" }),
      facilityNode("f2", { name: "101동 소방설비" }),
      facilityNode("f3", { name: "102동 승강기" }),
      locationNode("101동 지하", "101동 지하"),
    ];
    const links: GraphLink[] = [
      { source: "f1", target: "101동 지하", kind: "LOCATED_IN" },
      { source: "f2", target: "101동 지하", kind: "LOCATED_IN" },
    ];

    const result = facilitiesAtLocation(nodes, links, "101동 지하");

    expect(result.map((n) => n.pgId)).toEqual(["f1", "f2"]);
  });

  it("연결이 없으면 빈 배열", () => {
    expect(facilitiesAtLocation([facilityNode("f1")], [], "없는위치")).toEqual([]);
  });
});

describe("facilityIdForNode", () => {
  const nodes = {
    facility: facilityNode("f1"),
    incident: incidentNode("i1", false),
    maintenance: maintenanceNode("m1"),
    device: planNode("d1", "plan_device", "월패드(거실)"),
    room: planNode("p1:room:거실", "plan_room", "거실"),
    kind: planNode("p1:kind:월패드", "plan_kind", "월패드"),
  };
  const links: GraphLink[] = [
    { source: "f1", target: "i1", kind: "HAS_INCIDENT" },
    { source: "f1", target: "m1", kind: "HAS_MAINTENANCE" },
    { source: "p1", target: "p1:room:거실", kind: "HAS_ROOM" },
    { source: "p1:kind:월패드", target: "d1", kind: "HAS_DEVICE" },
    { source: "d1", target: "f1", kind: "LINKED_TO" },
  ];

  it("시설 노드는 자기 자신을 돌려준다", () => {
    expect(facilityIdForNode(nodes.facility, links)).toBe("f1");
  });

  it("장애·정비 이력은 부모 시설(inbound 링크의 source)로 귀결된다", () => {
    expect(facilityIdForNode(nodes.incident, links)).toBe("f1");
    expect(facilityIdForNode(nodes.maintenance, links)).toBe("f1");
  });

  it("도면 마커는 outbound LINKED_TO 의 target 설비로 귀결된다", () => {
    expect(facilityIdForNode(nodes.device, links)).toBe("f1");
  });

  it("배선되지 않은 마커는 null(상위 종류 허브를 시설로 오인하지 않는다)", () => {
    const unlinked = planNode("d2", "plan_device", "스위치(주방)");
    const linksWithoutWiring: GraphLink[] = [
      { source: "p1:kind:스위치", target: "d2", kind: "HAS_DEVICE" },
    ];

    expect(facilityIdForNode(unlinked, linksWithoutWiring)).toBeNull();
  });

  it("방·종류 허브는 상세 대상이 아니라 null", () => {
    expect(facilityIdForNode(nodes.room, links)).toBeNull();
    expect(facilityIdForNode(nodes.kind, links)).toBeNull();
  });
});

describe("estimatedInquiries", () => {
  const inquiries = [
    inquiry({ id: "a", title: "401동 누수", status: "received" }),
    inquiry({ id: "b", title: "누수", body: "401동 지하에서 물이 샙니다", status: "in_progress" }),
    inquiry({ id: "c", title: "401동 소음", status: "done" }),
    inquiry({ id: "d", title: "402동 누수", status: "received" }),
  ];

  it("동명이 제목·본문에 나오는 미종결 민원만 추정한다", () => {
    const result = estimatedInquiries(inquiries, "401동 기계실");

    expect(result.token).toBe("401동");
    expect(result.items.map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("완료된 민원은 제외한다", () => {
    expect(estimatedInquiries(inquiries, "401동").items.some((i) => i.id === "c")).toBe(false);
  });

  it("위치에 동 표기가 없으면 추정하지 않는다", () => {
    expect(estimatedInquiries(inquiries, "옥상")).toEqual({ token: null, items: [] });
  });
});
