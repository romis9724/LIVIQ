import { describe, it, expect } from "vitest";

import type { GraphLink, GraphNode, Inquiry, InquiryStatus } from "@/lib/api";
import {
  SYSTEM_COLOR_VARS,
  UNCLASSIFIED,
  UNCLASSIFIED_COLOR_VAR,
  INCIDENT_OPEN_COLOR_VAR,
  INCIDENT_RESOLVED_COLOR_VAR,
  MAINTENANCE_COLOR_VAR,
  buildingToken,
  centerByNodeId,
  estimatedInquiries,
  findFacilityByName,
  groupCenters,
  matchesBuilding,
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
    name: "정기 점검",
    type: null,
    location: null,
    status: null,
    at: "2026-07-02T00:00:00Z",
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
